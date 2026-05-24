//! `GenericDriver` — one driver that handles any model in the JSON catalogue
//! by reading its byte/bit/len record-decode spec at runtime.  Replaces the
//! handcoded per-device parsers; the per-device Rust files will be deleted
//! in the next commit once the registry is migrated.

use anyhow::{Context, Result, anyhow};
use bluer::Uuid;
use chrono::NaiveDate;

use crate::protocol::{
    ChannelConfig, LEGACY_PARENT_SERVICE_UUID, LEGACY_RX_UUIDS, LEGACY_TX_UUIDS,
    LEGACY_UNLOCK_UUID,
};
use crate::shared::{DeviceDriver, Endian, Record};
use crate::spec::{DeviceSpec, FieldSpec};

/// The HEM-7380T1 / HEM-7146T / HEM-7155T-V2 / HEM-7155T-V3 family — single-
/// channel BLE protocol under the alternative parent service UUID.
const ALT_PARENT_SERVICE_UUID: Uuid =
    Uuid::from_u128(0x0000fe4a_0000_1000_8000_00805f9b34fb);

pub struct GenericDriver {
    pub spec: DeviceSpec,
    /// `spec.model` lowercased once at construction so `name()` can return
    /// a borrow without re-allocating per call.
    lowercase_name: String,
    /// Materialised `&[u16]` slot for the trait's `user_start_addresses`
    /// return type — populated from `spec.addr1` and (if `user == 2`)
    /// `addr2`.
    user_starts: Vec<u16>,
    /// Same memory size for every user — replicated to match the trait's
    /// slice contract.
    per_user_counts: Vec<u16>,
}

impl GenericDriver {
    pub fn new(spec: DeviceSpec) -> Self {
        let lowercase_name = spec.model.to_ascii_lowercase();
        let mut user_starts = vec![spec.addr1];
        if spec.user == 2 {
            user_starts.push(spec.addr2);
        }
        let per_user_counts = vec![spec.memory; user_starts.len()];
        Self { spec, lowercase_name, user_starts, per_user_counts }
    }
}

impl DeviceDriver for GenericDriver {
    fn name(&self) -> &str { &self.lowercase_name }
    fn endian(&self) -> Endian {
        if self.spec.bigendian { Endian::Big } else { Endian::Little }
    }
    fn user_start_addresses(&self) -> &[u16] { &self.user_starts }
    fn per_user_records_count(&self) -> &[u16] { &self.per_user_counts }
    fn record_byte_size(&self) -> u8 { self.spec.step }
    fn transmission_block_size(&self) -> u8 {
        // Same rule the upstream port used: LE devices read in 16-byte
        // blocks; BE devices read in 0x38 = 56-byte super-blocks (the
        // meter answers in two BLE notifications and we reassemble).
        // The 7530T is the odd one out — BE but small 0x10 block.
        match self.spec.model.as_str() {
            "HEM-7530T" => 0x10,
            _ if self.spec.bigendian => 0x38,
            _ => 0x10,
        }
    }
    fn channel_config(&self) -> ChannelConfig {
        // Pick the BLE channel layout from the parent service UUID.  Models
        // on the legacy `ecbe3980-…` service use the 4-channel TX/RX layout;
        // models on the alternative `0000fe4a-…` service use a single
        // characteristic on each side.
        let parent: Uuid = self.spec.uuid.parse().unwrap_or(LEGACY_PARENT_SERVICE_UUID);
        if parent == ALT_PARENT_SERVICE_UUID {
            ChannelConfig {
                parent_service: ALT_PARENT_SERVICE_UUID,
                rx_uuids: vec![LEGACY_RX_UUIDS[0]],
                tx_uuids: vec![LEGACY_TX_UUIDS[0]],
                unlock_uuid: LEGACY_UNLOCK_UUID,
                requires_unlock: self.spec.pairing,
                supports_pairing: self.spec.pairing,
            }
        } else {
            ChannelConfig {
                parent_service: parent,
                rx_uuids: LEGACY_RX_UUIDS.to_vec(),
                tx_uuids: LEGACY_TX_UUIDS.to_vec(),
                unlock_uuid: LEGACY_UNLOCK_UUID,
                requires_unlock: self.spec.pairing,
                supports_pairing: self.spec.pairing,
            }
        }
    }
    fn os_bonding_only(&self) -> bool {
        // Models on the alternative service that don't do omblepy in-band
        // pairing (HEM-7146T, 7155T V2/V3, 7380T) use OS-level BLE bonding
        // exclusively.
        let parent: Uuid = self.spec.uuid.parse().unwrap_or(LEGACY_PARENT_SERVICE_UUID);
        parent == ALT_PARENT_SERVICE_UUID && !self.spec.pairing
    }
    fn parse_record(&self, bytes: &[u8]) -> Result<Record> {
        parse_record_with_spec(bytes, &self.spec)
    }
    // Time-sync isn't part of the ubpm JSON spec — left at the default
    // "not supported" so `--time-sync` returns a clean error rather than
    // writing garbage.  The hand-rolled hem_7361t.rs etc. drivers still
    // carry their own time-sync impls and stay registered until commit 3.
}

/// Decode an 8-byte record per ubpm's byte/bit/len convention.  Mirrors
/// `bits2Value()` in `DialogImport.cpp` line 778 plus the pairwise
/// byte-swap in lines 818-826 for big-endian devices.
pub fn parse_record_with_spec(bytes: &[u8], spec: &DeviceSpec) -> Result<Record> {
    if bytes.len() < 8 {
        return Err(anyhow!("record too short: {} bytes", bytes.len()));
    }
    // ubpm-style big-endian: pairwise byte swap before bit-slicing.
    let swapped: Vec<u8> = if spec.bigendian {
        let mut out = bytes.to_vec();
        let mut i = 0;
        while i + 1 < out.len() {
            out.swap(i, i + 1);
            i += 2;
        }
        out
    } else {
        bytes.to_vec()
    };
    let f = |fs: FieldSpec| -> u64 { extract_field(&swapped, fs) };
    let year = 2000 + f(spec.data.year) as i32;
    let month = f(spec.data.month) as u32;
    let day = f(spec.data.day) as u32;
    let hour = f(spec.data.hour) as u32;
    let minute = f(spec.data.minute) as u32;
    let second = (f(spec.data.second) as u32).min(59);
    let sys = 25 + f(spec.data.sys) as u16;
    let dia = f(spec.data.dia) as u16;
    let pulse = f(spec.data.bpm) as u16;
    let ihb = f(spec.data.ihb) as u8;
    let mov = f(spec.data.mov) as u8;
    let datetime = NaiveDate::from_ymd_opt(year, month, day)
        .and_then(|d| d.and_hms_opt(hour, minute, second))
        .with_context(|| {
            format!("invalid datetime y={year} m={month} d={day} h={hour} mi={minute} s={second}")
        })?;
    Ok(Record { datetime, sys, dia, pulse, mov, ihb })
}

fn extract_field(bytes: &[u8], spec: FieldSpec) -> u64 {
    let start = spec.byte * 8 + spec.bit;
    let end = start + spec.len;
    let mut value: u64 = 0;
    let mut shift: u32 = 0;
    for bit_idx in start..end {
        let byte_idx = bit_idx / 8;
        if byte_idx >= bytes.len() {
            break;
        }
        let bit_in_byte = bit_idx % 8;
        let bit = (bytes[byte_idx] >> bit_in_byte) & 1;
        value |= (bit as u64) << shift;
        shift += 1;
    }
    value
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spec::lookup;

    /// HEM-7361T is little-endian; build a known 16-byte record and assert
    /// every field decodes to the value we encoded.
    #[test]
    fn parse_round_trip_little_endian() {
        let spec = lookup("HEM-7361T").unwrap();
        // sys=120 (-25=95), dia=80, bpm=70, year=26, month=5, day=24,
        // hour=15, minute=30, second=45, mov=1, ihb=0.
        let mut rec = [0u8; 16];
        rec[0] = 95; // sys-25 (byte 0)
        rec[1] = 80; // dia (byte 1)
        rec[2] = 70; // bpm (byte 2)
        rec[3] = 26; // year low 6 bits (byte 3)
        // hour low 5 bits (byte 4 bits 0-4) = 15 = 0b01111
        // day low 3 bits in byte 4 bits 5-7 = 24 & 0b111 = 0; high 2 in byte 5 bits 0-1 = 24 >> 3 = 3
        // month bits 10-13 = byte 5 bits 2-5 = 5
        // ihb bit 14 = byte 5 bit 6 = 0
        // mov bit 15 = byte 5 bit 7 = 1
        rec[4] = 0b00000_01111;
        rec[5] = 0b1_0_0101_11;
        // second low 6 bits (byte 6 bits 0-5) = 45 = 0b101101
        // minute bits 6-11 = byte 6 bits 6-7 + byte 7 bits 0-3 = 30
        rec[6] = (30 << 6) as u8 | 45;
        rec[7] = (30 >> 2) as u8;
        let r = parse_record_with_spec(&rec, &spec).unwrap();
        assert_eq!(r.sys, 120);
        assert_eq!(r.dia, 80);
        assert_eq!(r.pulse, 70);
        assert_eq!(r.mov, 1);
        assert_eq!(r.ihb, 0);
        assert_eq!(r.datetime.format("%Y-%m-%d %H:%M:%S").to_string(), "2026-05-24 15:30:45");
    }

    /// HEM-7530T is big-endian — same fields, different byte order on the wire.
    /// After pairwise swap, the same byte/bit/len layout applies.
    #[test]
    fn parse_round_trip_big_endian() {
        let spec = lookup("HEM-7530T").unwrap();
        // Build the post-swap layout, then pair-swap to get the wire layout.
        let mut decoded = [0u8; 8];
        decoded[0] = 95;
        decoded[1] = 80;
        decoded[2] = 70;
        decoded[3] = 26;
        decoded[4] = 0b00000_01111;
        decoded[5] = 0b1_0_0101_11;
        decoded[6] = (30 << 6) as u8 | 45;
        decoded[7] = (30 >> 2) as u8;
        // Pair-swap back to wire format so parse_record_with_spec swaps it back.
        let mut wire = decoded;
        let mut i = 0;
        while i + 1 < wire.len() {
            wire.swap(i, i + 1);
            i += 2;
        }
        let r = parse_record_with_spec(&wire, &spec).unwrap();
        assert_eq!(r.sys, 120);
        assert_eq!(r.dia, 80);
        assert_eq!(r.pulse, 70);
        assert_eq!(r.mov, 1);
        assert_eq!(r.ihb, 0);
    }

    #[test]
    fn generic_driver_picks_alt_uuid_layout_for_7380t() {
        let spec = lookup("HEM-7380T").unwrap();
        let driver = GenericDriver::new(spec);
        let cfg = driver.channel_config();
        assert_eq!(cfg.parent_service, ALT_PARENT_SERVICE_UUID);
        assert_eq!(cfg.rx_uuids.len(), 1);
        assert_eq!(cfg.tx_uuids.len(), 1);
        assert!(!cfg.requires_unlock);
        assert!(driver.os_bonding_only());
    }

    #[test]
    fn generic_driver_picks_legacy_uuid_layout_for_7361t() {
        let spec = lookup("HEM-7361T").unwrap();
        let driver = GenericDriver::new(spec);
        let cfg = driver.channel_config();
        assert_eq!(cfg.parent_service, LEGACY_PARENT_SERVICE_UUID);
        assert_eq!(cfg.rx_uuids.len(), 4);
        assert_eq!(cfg.tx_uuids.len(), 4);
        assert!(cfg.requires_unlock);
    }
}
