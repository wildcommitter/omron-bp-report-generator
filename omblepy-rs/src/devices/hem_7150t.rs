use anyhow::Result;

use crate::shared::{DeviceDriver, Endian, Record, SettingsLayout};

use super::common::{parse_modern_le_record, sync_time_modern_le};

pub struct Hem7150t;

impl DeviceDriver for Hem7150t {
    fn name(&self) -> &str { "hem-7150t" }
    fn endian(&self) -> Endian { Endian::Little }
    fn user_start_addresses(&self) -> &[u16] { &[0x0098] }
    fn per_user_records_count(&self) -> &[u16] { &[60] }
    fn record_byte_size(&self) -> u8 { 0x10 }
    fn transmission_block_size(&self) -> u8 { 0x10 }
    fn settings_layout(&self) -> Option<SettingsLayout> {
        Some(SettingsLayout {
            read_address: 0x0010,
            write_address: 0x0054,
            unread_records_bytes: (0x00, 0x10),
            time_sync_bytes: (0x2C, 0x3C),
        })
    }
    fn supports_time_sync(&self) -> bool { true }
    fn parse_record(&self, bytes: &[u8]) -> Result<Record> { parse_modern_le_record(bytes) }
    fn sync_with_system_time(&self, slice: &mut [u8]) -> Result<()> { sync_time_modern_le(slice) }
}
