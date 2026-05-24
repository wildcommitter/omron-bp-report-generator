use anyhow::Result;

use crate::shared::{DeviceDriver, Endian, Record, SettingsLayout};

use super::common::parse_old_be_record_v1;

pub struct Hem6232t;

impl DeviceDriver for Hem6232t {
    fn name(&self) -> &str { "hem-6232t" }
    fn endian(&self) -> Endian { Endian::Big }
    fn user_start_addresses(&self) -> &[u16] { &[0x02e8, 0x0860] }
    fn per_user_records_count(&self) -> &[u16] { &[100, 100] }
    fn record_byte_size(&self) -> u8 { 0x0e }
    fn transmission_block_size(&self) -> u8 { 0x38 }
    fn settings_layout(&self) -> Option<SettingsLayout> {
        // Upstream marks the time-sync byte range as "probably not correct",
        // but the unread-records counter at 0x00..0x08 has been confirmed.
        Some(SettingsLayout {
            read_address: 0x0260,
            write_address: 0x02A4,
            unread_records_bytes: (0x00, 0x08),
            time_sync_bytes: (0x14, 0x1e),
        })
    }
    // upstream's hem-6232t raises "Not supported yet" in syncWithSystemTime
    // because the byte layout isn't confirmed.  Mirror that.
    fn parse_record(&self, bytes: &[u8]) -> Result<Record> { parse_old_be_record_v1(bytes) }
}
