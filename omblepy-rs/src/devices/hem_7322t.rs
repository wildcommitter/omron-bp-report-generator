use anyhow::Result;

use crate::shared::{DeviceDriver, Endian, Record, SettingsLayout};

use super::common::{parse_old_be_record_v2, sync_time_old_be};

pub struct Hem7322t;

impl DeviceDriver for Hem7322t {
    fn name(&self) -> &'static str { "hem-7322t" }
    fn endian(&self) -> Endian { Endian::Big }
    fn user_start_addresses(&self) -> &[u16] { &[0x02ac, 0x0824] }
    fn per_user_records_count(&self) -> &[u16] { &[100, 100] }
    fn record_byte_size(&self) -> u8 { 0x0e }
    fn transmission_block_size(&self) -> u8 { 0x38 }
    fn settings_layout(&self) -> Option<SettingsLayout> {
        Some(SettingsLayout {
            read_address: 0x0260,
            write_address: 0x0286,
            unread_records_bytes: (0x00, 0x08),
            time_sync_bytes: (0x14, 0x1e),
        })
    }
    fn supports_time_sync(&self) -> bool { true }
    fn parse_record(&self, bytes: &[u8]) -> Result<Record> { parse_old_be_record_v2(bytes) }
    fn sync_with_system_time(&self, slice: &mut [u8]) -> Result<()> { sync_time_old_be(slice) }
}
