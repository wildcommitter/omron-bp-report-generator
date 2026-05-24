//! Write Omron records into a CSV file the Python pipeline can ingest.
//!
//! Schema matches the user's existing OMRON-Complete-style export:
//!
//! ```csv
//! Fecha,Hora,Sistólica (mmHg),Diastólica (mmHg),Pulso (ppm)
//! 20 may. 2026,08:53,109,62,77
//! ```
//!
//! Two helpers:
//!
//! * [`write_records`] writes one CSV file from a flat list of records.
//! * [`flatten_users`] takes the per-user `Vec<Vec<Record>>` that
//!   `shared::read_records` returns and concatenates it into a single
//!   chronologically-sorted, duplicate-free stream.

use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::Path;

use anyhow::{Context, Result};
use chrono::Datelike;

use crate::shared::Record;

const HEADERS: &[&str] = &[
    "Fecha",
    "Hora",
    "Sistólica (mmHg)",
    "Diastólica (mmHg)",
    "Pulso (ppm)",
];

/// Spanish month abbreviations matching what the OMRON Complete app
/// exports — `bp_utils.load_omron_csv()` already knows how to parse
/// these, so the Rust output round-trips through the same `parse_dt`.
const SPANISH_MONTHS: [&str; 13] = [
    "", "ene.", "feb.", "mar.", "abr.", "may.", "jun.",
    "jul.", "ago.", "sep.", "oct.", "nov.", "dic.",
];

fn format_date_es(rec: &Record) -> String {
    format!(
        "{} {} {}",
        rec.datetime.day(),
        SPANISH_MONTHS[rec.datetime.month() as usize],
        rec.datetime.year()
    )
}

fn format_time(rec: &Record) -> String {
    rec.datetime.format("%H:%M").to_string()
}

/// Flatten the per-user record vectors into one chronologically-sorted
/// stream with duplicates (same datetime) removed. Mirrors what
/// `appendCsv` does in upstream omblepy when it merges new records with
/// the previous CSV.
pub fn flatten_users(users: Vec<Vec<Record>>) -> Vec<Record> {
    let mut flat: Vec<Record> = users.into_iter().flatten().collect();
    flat.sort_by_key(|r| r.datetime);
    flat.dedup_by_key(|r| r.datetime);
    flat
}

pub fn write_records(path: &Path, records: &[Record]) -> Result<()> {
    let file = File::create(path)
        .with_context(|| format!("create csv at {}", path.display()))?;
    let mut w = BufWriter::new(file);
    writeln!(w, "{}", HEADERS.join(","))?;
    for r in records {
        writeln!(
            w,
            "{},{},{},{},{}",
            format_date_es(r),
            format_time(r),
            r.sys,
            r.dia,
            r.pulse
        )?;
    }
    w.flush().context("flush csv writer")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{NaiveDate, NaiveDateTime};

    fn rec(dt: NaiveDateTime, sys: u16, dia: u16, pulse: u16) -> Record {
        Record { datetime: dt, sys, dia, pulse, mov: 0, ihb: 0 }
    }

    #[test]
    fn date_format_matches_existing_input() {
        // The user's existing input.csv has rows like "20 may. 2026,08:53".
        let dt = NaiveDate::from_ymd_opt(2026, 5, 20)
            .unwrap()
            .and_hms_opt(8, 53, 0)
            .unwrap();
        let r = rec(dt, 109, 62, 77);
        assert_eq!(format_date_es(&r), "20 may. 2026");
        assert_eq!(format_time(&r), "08:53");
    }

    #[test]
    fn flatten_dedups_by_datetime() {
        let dt1 = NaiveDate::from_ymd_opt(2026, 5, 1).unwrap().and_hms_opt(8, 0, 0).unwrap();
        let dt2 = NaiveDate::from_ymd_opt(2026, 5, 2).unwrap().and_hms_opt(8, 0, 0).unwrap();
        let users = vec![
            vec![rec(dt2, 110, 70, 70), rec(dt1, 100, 60, 60)],
            // a duplicate of dt1 from another user — should collapse
            vec![rec(dt1, 101, 61, 61)],
        ];
        let flat = flatten_users(users);
        assert_eq!(flat.len(), 2);
        assert_eq!(flat[0].datetime, dt1);
        assert_eq!(flat[1].datetime, dt2);
    }
}
