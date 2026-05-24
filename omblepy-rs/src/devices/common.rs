//! Shared record-parse + time-sync helpers used by multiple device drivers.

use anyhow::{Context, Result, bail};
use chrono::{Datelike, Local, NaiveDate, Timelike};

use crate::shared::{Endian, Record, bits_to_int};

/// Decode the 14-byte big-endian record layout used by HEM-7322T and
/// HEM-7600T: year at bits 16–23, then mov/ihb at bits 32/33 (in that
/// order).
pub fn parse_old_be_record_v2(bytes: &[u8]) -> Result<Record> {
    decode_be_common(bytes, /* year_first_bit = */ 16, /* mov_first = */ true)
}

/// Decode the 14-byte big-endian record layout used by HEM-6232T and
/// HEM-7530T: year at bits 18–23, then ihb/mov at bits 32/33 (ihb first).
pub fn parse_old_be_record_v1(bytes: &[u8]) -> Result<Record> {
    decode_be_common(bytes, /* year_first_bit = */ 18, /* mov_first = */ false)
}

fn decode_be_common(bytes: &[u8], year_first_bit: usize, mov_first: bool) -> Result<Record> {
    if bytes.len() < 14 {
        bail!("record too short: {} bytes", bytes.len());
    }
    let e = Endian::Big;
    let dia = bits_to_int(bytes, 0, 7, e) as u16;
    let sys = bits_to_int(bytes, 8, 15, e) as u16 + 25;
    let year = bits_to_int(bytes, year_first_bit, 23, e) + 2000;
    let pulse = bits_to_int(bytes, 24, 31, e) as u16;
    let (mov, ihb) = if mov_first {
        (
            bits_to_int(bytes, 32, 32, e) as u8,
            bits_to_int(bytes, 33, 33, e) as u8,
        )
    } else {
        (
            bits_to_int(bytes, 33, 33, e) as u8,
            bits_to_int(bytes, 32, 32, e) as u8,
        )
    };
    let month = bits_to_int(bytes, 34, 37, e);
    let day = bits_to_int(bytes, 38, 42, e);
    let hour = bits_to_int(bytes, 43, 47, e);
    let minute = bits_to_int(bytes, 52, 57, e);
    let second = bits_to_int(bytes, 58, 63, e).min(59);
    let datetime = NaiveDate::from_ymd_opt(year as i32, month as u32, day as u32)
        .and_then(|d| d.and_hms_opt(hour as u32, minute as u32, second as u32))
        .with_context(|| {
            format!("invalid datetime year={year} month={month} day={day} hour={hour} min={minute} sec={second}")
        })?;
    Ok(Record { datetime, sys, dia, pulse, mov, ihb })
}

/// Write the host's current time into the time-sync slice used by
/// HEM-7322T / HEM-7600T (10 bytes: first 2 reserved, then
/// month/year/hour/day/second/minute, then 0x00 + checksum).
pub fn sync_time_old_be(slice: &mut [u8]) -> Result<()> {
    if slice.len() != 10 {
        bail!("time-sync slice must be 10 bytes, got {}", slice.len());
    }
    let now = Local::now().naive_local();
    slice[2] = now.month() as u8;
    slice[3] = (now.year() - 2000) as u8;
    slice[4] = now.hour() as u8;
    slice[5] = now.day() as u8;
    slice[6] = now.second() as u8;
    slice[7] = now.minute() as u8;
    slice[8] = 0x00;
    let checksum: u8 = slice[..9].iter().fold(0u8, |a, &b| a.wrapping_add(b));
    slice[9] = checksum;
    Ok(())
}

/// Decode the "modern little-endian" record layout used by HEM-7150T,
/// 7155T, 7342T, 7361T (16 bytes, bit positions 68–127). The first 8 bytes
/// are reserved (zero in practice); the upper 8 bytes carry the reading.
pub fn parse_modern_le_record(bytes: &[u8]) -> Result<Record> {
    if bytes.len() < 16 {
        bail!("record too short: {} bytes", bytes.len());
    }
    let endian = Endian::Little;
    let minute = bits_to_int(bytes, 68, 73, endian);
    let second = bits_to_int(bytes, 74, 79, endian).min(59);
    let mov = bits_to_int(bytes, 80, 80, endian) as u8;
    let ihb = bits_to_int(bytes, 81, 81, endian) as u8;
    let month = bits_to_int(bytes, 82, 85, endian);
    let day = bits_to_int(bytes, 86, 90, endian);
    let hour = bits_to_int(bytes, 91, 95, endian);
    let year = bits_to_int(bytes, 98, 103, endian) + 2000;
    let pulse = bits_to_int(bytes, 104, 111, endian) as u16;
    let dia = bits_to_int(bytes, 112, 119, endian) as u16;
    let sys = bits_to_int(bytes, 120, 127, endian) as u16 + 25;
    let datetime = NaiveDate::from_ymd_opt(year as i32, month as u32, day as u32)
        .and_then(|d| d.and_hms_opt(hour as u32, minute as u32, second as u32))
        .with_context(|| {
            format!("invalid datetime year={year} month={month} day={day} hour={hour} min={minute} sec={second}")
        })?;
    Ok(Record { datetime, sys, dia, pulse, mov, ihb })
}

/// Write the host's current time into the 16-byte time-sync slice used by
/// modern little-endian devices.  First 8 bytes are kept intact; the next 6
/// bytes hold year/month/day/hour/minute/second (year-2000), then a one-byte
/// checksum + zero padding.
pub fn sync_time_modern_le(slice: &mut [u8]) -> Result<()> {
    if slice.len() != 16 {
        bail!("time-sync slice must be 16 bytes, got {}", slice.len());
    }
    let now = Local::now().naive_local();
    slice[8] = (now.year() - 2000) as u8;
    slice[9] = now.month() as u8;
    slice[10] = now.day() as u8;
    slice[11] = now.hour() as u8;
    slice[12] = now.minute() as u8;
    slice[13] = now.second() as u8;
    let checksum: u8 = slice[..14].iter().fold(0u8, |a, &b| a.wrapping_add(b));
    slice[14] = checksum;
    slice[15] = 0x00;
    Ok(())
}
