//! Shared driver logic: the parts of `sharedDriver.py` that don't change
//! per device. Concrete device types live in `crate::devices::*` and
//! implement `DeviceDriver` with their address tables and parse rules.

use anyhow::{Context, Result, bail};
use chrono::NaiveDateTime;
use tracing::{info, warn};

use crate::protocol::{ChannelConfig, Protocol};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Endian {
    Big,
    Little,
}

#[derive(Debug, Clone)]
pub struct Record {
    pub datetime: NaiveDateTime,
    pub sys: u16,
    pub dia: u16,
    pub pulse: u16,
    pub mov: u8,
    pub ihb: u8,
}

#[derive(Debug, Clone, Copy)]
pub struct SettingsLayout {
    pub read_address: u16,
    pub write_address: u16,
    pub unread_records_bytes: (usize, usize),
    pub time_sync_bytes: (usize, usize),
}

/// Trait every device-specific driver implements.
pub trait DeviceDriver: Send + Sync {
    fn name(&self) -> &'static str;
    fn endian(&self) -> Endian;
    fn user_start_addresses(&self) -> &[u16];
    fn per_user_records_count(&self) -> &[u16];
    fn record_byte_size(&self) -> u8;
    fn transmission_block_size(&self) -> u8;
    fn channel_config(&self) -> ChannelConfig {
        ChannelConfig::default()
    }
    /// Some devices (notably HEM-7380T1) don't expose a settings region, so
    /// neither `--new-rec-only` nor `--time-sync` is available; the driver
    /// returns `None` to disable those features cleanly.
    fn settings_layout(&self) -> Option<SettingsLayout> {
        None
    }
    fn supports_time_sync(&self) -> bool {
        false
    }
    fn parse_record(&self, bytes: &[u8]) -> Result<Record>;
    /// Mutate the time-sync slice of the cached settings in place. Default
    /// is "not supported"; overridden by drivers that know the byte layout.
    fn sync_with_system_time(&self, _time_sync_slice: &mut [u8]) -> Result<()> {
        bail!("time sync not supported for {}", self.name())
    }
}

/// `int.from_bytes(bytes, endian)` shifted to extract bits [first..=last]
/// of the resulting big integer, indexed from the most-significant bit
/// (bit 0) downward. Mirrors `_bytearrayBitsToInt` in sharedDriver.py.
pub fn bits_to_int(bytes: &[u8], first: usize, last: usize, endian: Endian) -> u64 {
    let mut big: u128 = 0;
    match endian {
        Endian::Big => {
            for &b in bytes {
                big = (big << 8) | b as u128;
            }
        }
        Endian::Little => {
            for (i, &b) in bytes.iter().enumerate() {
                big |= (b as u128) << (i * 8);
            }
        }
    }
    let total_bits = bytes.len() * 8;
    let shift = total_bits - (last + 1);
    let num_valid = last - first + 1;
    let mask: u128 = (1u128 << num_valid) - 1;
    ((big >> shift) & mask) as u64
}

#[derive(Debug, Clone, Copy)]
pub struct ReadCommand {
    pub address: u16,
    pub size: usize,
}

/// Given a user's record-count and last-written slot, compute the EEPROM
/// read locations that retrieve the unread records in chronological order.
/// One range if the ring buffer hasn't wrapped, two if it has.
pub fn calc_ring_buffer_read_locations(
    driver: &dyn DeviceDriver,
    user_idx: usize,
    unread_records: u16,
    last_written_slot: u16,
) -> Vec<ReadCommand> {
    let rec_size = driver.record_byte_size() as u16;
    let user_start = driver.user_start_addresses()[user_idx];
    let user_max = driver.per_user_records_count()[user_idx];
    let mut out = Vec::new();
    if last_written_slot < unread_records {
        out.push(ReadCommand {
            address: user_start,
            size: rec_size as usize * last_written_slot as usize,
        });
        out.push(ReadCommand {
            address: user_start
                + (user_max + last_written_slot - unread_records) * rec_size,
            size: rec_size as usize * (unread_records - last_written_slot) as usize,
        });
    } else {
        out.push(ReadCommand {
            address: user_start + (last_written_slot - unread_records) * rec_size,
            size: rec_size as usize * unread_records as usize,
        });
    }
    out
}

/// Build the per-user read-command list for "every slot" (matches
/// `_getReadCommands_AllRecords`).
fn read_commands_all_records(driver: &dyn DeviceDriver) -> Vec<Vec<ReadCommand>> {
    driver
        .user_start_addresses()
        .iter()
        .enumerate()
        .map(|(i, &addr)| {
            vec![ReadCommand {
                address: addr,
                size: driver.record_byte_size() as usize
                    * driver.per_user_records_count()[i] as usize,
            }]
        })
        .collect()
}

/// Build the per-user read-command list for "only unread records" using
/// the cached settings bytes (matches `_getReadCommands_OnlyNewRecords`).
fn read_commands_new_records(
    driver: &dyn DeviceDriver,
    cached_settings: &[u8],
) -> Result<Vec<Vec<ReadCommand>>> {
    let layout = driver
        .settings_layout()
        .ok_or_else(|| anyhow::anyhow!("device has no settings region"))?;
    let info = &cached_settings[layout.unread_records_bytes.0..layout.unread_records_bytes.1];
    let endian = driver.endian();
    let mut out = Vec::new();
    for user_idx in 0..driver.user_start_addresses().len() {
        let last_written =
            bits_to_int(&info[2 * user_idx..2 * user_idx + 2], 8, 15, endian) as u16;
        let unread =
            bits_to_int(&info[2 * user_idx + 4..2 * user_idx + 6], 8, 15, endian) as u16;
        info!(
            "user{}: ring-buffer slot {}, {} unread",
            user_idx + 1,
            last_written,
            unread
        );
        out.push(calc_ring_buffer_read_locations(
            driver,
            user_idx,
            unread,
            last_written,
        ));
    }
    Ok(out)
}

/// Special "no new records" marker writen into the unread-record counter
/// when `--new-rec-only` runs. Mirrors `resetUnreadRecordsCounter`.
fn reset_unread_counter_in_cache(
    driver: &dyn DeviceDriver,
    cached_settings: &mut [u8],
) -> Result<()> {
    let layout = driver
        .settings_layout()
        .ok_or_else(|| anyhow::anyhow!("device has no settings region"))?;
    let section = &mut cached_settings
        [layout.unread_records_bytes.0..layout.unread_records_bytes.1];
    if section.len() < 8 {
        bail!("unread-records section too short to reset");
    }
    let marker = match driver.endian() {
        Endian::Little => [0x00u8, 0x80u8],
        Endian::Big => [0x80u8, 0x00u8],
    };
    section[4..6].copy_from_slice(&marker);
    section[6..8].copy_from_slice(&marker);
    Ok(())
}

/// High-level "do a session": unlock, start transmission, optionally cache
/// settings, read records (all or unread-only), apply post-read writebacks
/// (reset unread counter, write system time), end transmission. Returns a
/// vector of per-user record lists.
pub async fn read_records(
    proto: &mut Protocol,
    driver: &dyn DeviceDriver,
    pairing_key: &[u8; 16],
    use_unread_counter: bool,
    sync_time: bool,
) -> Result<Vec<Vec<Record>>> {
    proto.unlock(pairing_key).await.context("unlock device")?;
    proto.start_transmission().await?;

    let layout = driver.settings_layout();
    let mut cached_settings: Vec<u8> = Vec::new();
    if (use_unread_counter || sync_time) && layout.is_some() {
        let s = layout.unwrap();
        let total = (s.write_address - s.read_address) as usize;
        cached_settings = vec![0u8; total];
        for section in [s.unread_records_bytes, s.time_sync_bytes] {
            let section_size = section.1 - section.0;
            if section_size >= 54 {
                bail!("settings section too big for a single read ({section_size} bytes)");
            }
            let bytes = proto
                .read_continuous(
                    s.read_address + section.0 as u16,
                    section_size,
                    section_size as u8,
                )
                .await
                .context("cache settings section")?;
            cached_settings[section.0..section.1].copy_from_slice(&bytes);
        }
    } else if use_unread_counter || sync_time {
        bail!("device does not support --new-rec-only or --time-sync");
    }

    let read_commands = if use_unread_counter {
        read_commands_new_records(driver, &cached_settings)?
    } else {
        read_commands_all_records(driver)
    };

    info!("reading records, this can take a while; raise RUST_LOG=debug for progress");
    let rec_size = driver.record_byte_size() as usize;
    let block_size = driver.transmission_block_size();
    let mut all_records: Vec<Vec<Record>> = Vec::with_capacity(read_commands.len());
    for (user_idx, cmds) in read_commands.iter().enumerate() {
        let mut concat = Vec::new();
        for cmd in cmds {
            let bytes = proto
                .read_continuous(cmd.address, cmd.size, block_size)
                .await
                .with_context(|| format!("read user{} at {:#x}", user_idx + 1, cmd.address))?;
            concat.extend_from_slice(&bytes);
        }
        let mut user_records = Vec::new();
        let empty: Vec<u8> = vec![0xff; rec_size];
        for chunk in concat.chunks_exact(rec_size) {
            if chunk == empty.as_slice() {
                continue;
            }
            match driver.parse_record(chunk) {
                Ok(r) => user_records.push(r),
                Err(e) => warn!("user{}: parse error: {e}, ignoring", user_idx + 1),
            }
        }
        all_records.push(user_records);
    }

    if use_unread_counter {
        reset_unread_counter_in_cache(driver, &mut cached_settings)?;
    }
    if sync_time {
        let s = layout.unwrap();
        driver.sync_with_system_time(
            &mut cached_settings[s.time_sync_bytes.0..s.time_sync_bytes.1],
        )?;
        let slice = &cached_settings[s.time_sync_bytes.0..s.time_sync_bytes.1];
        proto
            .write_continuous(
                s.write_address + s.time_sync_bytes.0 as u16,
                slice,
                slice.len() as u8,
            )
            .await?;
    }
    if use_unread_counter {
        let s = layout.unwrap();
        let slice = &cached_settings[s.unread_records_bytes.0..s.unread_records_bytes.1];
        proto
            .write_continuous(
                s.write_address + s.unread_records_bytes.0 as u16,
                slice,
                slice.len() as u8,
            )
            .await?;
    }

    proto.end_transmission().await?;
    Ok(all_records)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveDate;

    #[test]
    fn bits_to_int_extracts_low_byte_under_either_endian() {
        // 2-byte field, last 8 bits.
        let big = bits_to_int(&[0xab, 0xcd], 8, 15, Endian::Big);
        let little = bits_to_int(&[0xab, 0xcd], 8, 15, Endian::Little);
        // Big-endian: int = 0xabcd, low byte = 0xcd.
        assert_eq!(big, 0xcd);
        // Little-endian: int = 0xcdab, low byte = 0xab.
        assert_eq!(little, 0xab);
    }

    #[test]
    fn bits_to_int_handles_long_input() {
        // 16-byte buffer — exactly what the modern Omron record parser uses.
        let mut buf = [0u8; 16];
        // Put 0x3f (6-bit value) into the top of byte 8 in little-endian.
        // Little-endian: byte 0 is LSB. After conversion, byte 8 sits at bits
        // 64..72 of the integer (LSB-first). Bit positions in the function
        // are MSB-first, so byte 8 is at positions (128 - 72)..(128 - 64) =
        // 56..64. Extract bits 56..63.
        buf[8] = 0x3f;
        let v = bits_to_int(&buf, 56, 63, Endian::Little);
        assert_eq!(v, 0x3f);
    }

    struct FakeDriver;
    impl DeviceDriver for FakeDriver {
        fn name(&self) -> &'static str { "fake" }
        fn endian(&self) -> Endian { Endian::Little }
        fn user_start_addresses(&self) -> &[u16] { &[0x100] }
        fn per_user_records_count(&self) -> &[u16] { &[10] }
        fn record_byte_size(&self) -> u8 { 16 }
        fn transmission_block_size(&self) -> u8 { 16 }
        fn parse_record(&self, _bytes: &[u8]) -> Result<Record> {
            Ok(Record {
                datetime: NaiveDate::from_ymd_opt(2026, 1, 1).unwrap().and_hms_opt(0, 0, 0).unwrap(),
                sys: 120, dia: 80, pulse: 60, mov: 0, ihb: 0,
            })
        }
    }

    #[test]
    fn ring_buffer_simple_case_no_wrap() {
        // Slot 7 written last, 3 unread → read from slot 4 onward.
        let cmds = calc_ring_buffer_read_locations(&FakeDriver, 0, 3, 7);
        assert_eq!(cmds.len(), 1);
        assert_eq!(cmds[0].address, 0x100 + 4 * 16);
        assert_eq!(cmds[0].size, 3 * 16);
    }

    #[test]
    fn ring_buffer_wrap_splits_into_two_reads() {
        // Slot 2 written last, 5 unread → 2 records at start + 3 records at
        // wrap-around tail.
        let cmds = calc_ring_buffer_read_locations(&FakeDriver, 0, 5, 2);
        assert_eq!(cmds.len(), 2);
        assert_eq!(cmds[0].address, 0x100);
        assert_eq!(cmds[0].size, 2 * 16);
        // wrap tail: user_start + (max + last_written - unread) * rec_size
        //          = 0x100 + (10 + 2 - 5) * 16 = 0x100 + 7 * 16
        assert_eq!(cmds[1].address, 0x100 + 7 * 16);
        assert_eq!(cmds[1].size, 3 * 16);
    }
}
