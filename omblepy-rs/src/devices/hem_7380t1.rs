use anyhow::{Result, bail};
use bluer::Uuid;
use chrono::NaiveDate;

use crate::protocol::ChannelConfig;
use crate::shared::{DeviceDriver, Endian, Record};

const PARENT_SERVICE: Uuid = Uuid::from_u128(0x0000fe4a_0000_1000_8000_00805f9b34fb);
const RX_UUID: Uuid = Uuid::from_u128(0x49123040_aee8_11e1_a74d_0002a5d5c51b);
const TX_UUID: Uuid = Uuid::from_u128(0xdb5b55e0_aee7_11e1_965e_0002a5d5c51b);
const UNLOCK_UUID: Uuid = Uuid::from_u128(0xb305b680_aee7_11e1_a730_0002a5d5c51b);

pub struct Hem7380t1;

impl DeviceDriver for Hem7380t1 {
    fn name(&self) -> &str { "hem-7380t1" }
    fn endian(&self) -> Endian { Endian::Little }
    fn user_start_addresses(&self) -> &[u16] { &[0x01C4, 0x0804] }
    fn per_user_records_count(&self) -> &[u16] { &[100, 100] }
    fn record_byte_size(&self) -> u8 { 0x10 }
    fn transmission_block_size(&self) -> u8 { 0x38 }
    fn channel_config(&self) -> ChannelConfig {
        ChannelConfig {
            parent_service: PARENT_SERVICE,
            rx_uuids: vec![RX_UUID],
            tx_uuids: vec![TX_UUID],
            unlock_uuid: UNLOCK_UUID,
            requires_unlock: false,
            supports_pairing: false,
        }
    }
    // No settings region → no `--new-rec-only` or `--time-sync` support
    // (default `settings_layout` returns None).
    fn os_bonding_only(&self) -> bool { true }
    fn parse_record(&self, bytes: &[u8]) -> Result<Record> {
        if bytes.len() < 16 {
            bail!("record too short: {} bytes", bytes.len());
        }
        let raw_sys = bytes[0];
        if raw_sys > 0xE1 {
            bail!("record slot empty (raw sys = {raw_sys:#x})");
        }
        let sys = raw_sys as u16 + 25;
        let dia = bytes[1] as u16;
        let pulse = bytes[2] as u16;
        let year = 2000 + (bytes[3] & 0x3F) as i32;
        let flags1: u16 = bytes[4] as u16 | ((bytes[5] as u16) << 8);
        let flags2: u16 = bytes[6] as u16 | ((bytes[7] as u16) << 8);
        let hour = (flags1 & 0x1F) as u32;
        let day = ((flags1 >> 5) & 0x1F) as u32;
        let month = ((flags1 >> 10) & 0x0F) as u32;
        let ihb = ((flags1 >> 14) & 0x01) as u8;
        let mov = ((flags1 >> 15) & 0x01) as u8;
        let second = ((flags2 & 0x3F) as u32).min(59);
        let minute = ((flags2 >> 6) & 0x3F) as u32;
        let datetime = NaiveDate::from_ymd_opt(year, month, day)
            .and_then(|d| d.and_hms_opt(hour, minute, second))
            .ok_or_else(|| anyhow::anyhow!(
                "invalid datetime y={year} m={month} d={day} h={hour} mi={minute} s={second}"
            ))?;
        Ok(Record { datetime, sys, dia, pulse, mov, ihb })
    }
}
