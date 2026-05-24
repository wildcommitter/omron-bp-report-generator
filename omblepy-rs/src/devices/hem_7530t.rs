use anyhow::Result;

use crate::shared::{DeviceDriver, Endian, Record};

use super::common::parse_old_be_record_v1;

pub struct Hem7530t;

impl DeviceDriver for Hem7530t {
    fn name(&self) -> &'static str { "hem-7530t" }
    fn endian(&self) -> Endian { Endian::Big }
    fn user_start_addresses(&self) -> &[u16] { &[0x02e8] }
    fn per_user_records_count(&self) -> &[u16] { &[90] }
    fn record_byte_size(&self) -> u8 { 0x0e }
    fn transmission_block_size(&self) -> u8 { 0x10 }
    // Upstream comments out settingsUnreadRecordsBytes + settingsTimeSyncBytes
    // for 7530T, so neither --new-rec-only nor --time-sync is supported.
    fn parse_record(&self, bytes: &[u8]) -> Result<Record> { parse_old_be_record_v1(bytes) }
}
