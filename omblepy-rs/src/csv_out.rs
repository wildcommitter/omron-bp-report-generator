//! Write Omron records into a CSV file the Python pipeline can ingest, and
//! optionally merge the result into an existing input.csv via the shared
//! `omron_merge.sh` script.
//!
//! Schema matches the user's existing OMRON-Complete-style export — same
//! 17 columns, same trailing dashes and blanks, so the merge script's
//! exact-header check passes when stacking a daemon-written CSV against
//! a hand-exported one.

use std::fs;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{Context, Result, bail};
use chrono::Datelike;

use crate::shared::Record;

/// Verbatim header of the user's `input.csv`.  17 columns: the five that
/// `bp_utils.load_omron_csv()` actually reads, plus twelve placeholders the
/// OMRON Complete export carries and the merge script's header-equality
/// check requires.
pub const HEADER: &str =
    "Fecha,Hora,Sistólica (mmHg),Diastólica (mmHg),Pulso (ppm),Síntomas,Consumido,TruRead,\
Se detectó latido arrítmico,Movimiento corporal,Guía de envoltura del manguito,\
Indicador de posicionamiento,Modo de medición,Error n.º,Posible AFib,Dispositivo,Notas";

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
/// stream with same-datetime duplicates removed.
pub fn flatten_users(users: Vec<Vec<Record>>) -> Vec<Record> {
    let mut flat: Vec<Record> = users.into_iter().flatten().collect();
    flat.sort_by_key(|r| r.datetime);
    flat.dedup_by_key(|r| r.datetime);
    flat
}

fn write_row(w: &mut impl Write, r: &Record) -> Result<()> {
    // Columns 6-17 mirror the user's input.csv exactly: literal dashes and
    // single spaces where OMRON's app leaves blanks.  The fields the meter
    // *does* know (mov, ihb) are still left blank because the analyze
    // pipeline doesn't read them and emitting "0"/"1" risks confusing other
    // exports.
    writeln!(
        w,
        "{date},{time},{sys},{dia},{pulse},-,-,-, , , , , ,-, ,omblepy-rs,-",
        date = format_date_es(r),
        time = format_time(r),
        sys = r.sys,
        dia = r.dia,
        pulse = r.pulse,
    )?;
    Ok(())
}

pub fn write_records(path: &Path, records: &[Record]) -> Result<()> {
    let file = fs::File::create(path)
        .with_context(|| format!("create csv at {}", path.display()))?;
    let mut w = BufWriter::new(file);
    writeln!(w, "{HEADER}")?;
    for r in records {
        write_row(&mut w, r)?;
    }
    w.flush().context("flush csv writer")?;
    Ok(())
}

/// Merge `new_csv` into `target`, deduplicating via `omron_merge.sh`.
/// When `target` doesn't exist yet the new file is just copied into place.
pub fn merge_into(target: &Path, new_csv: &Path, merge_script: &Path) -> Result<()> {
    if !target.exists() {
        fs::copy(new_csv, target).with_context(|| {
            format!(
                "copy {} → {} (target did not exist)",
                new_csv.display(),
                target.display()
            )
        })?;
        return Ok(());
    }
    // omron_merge.sh truncates its output before reading inputs, so we must
    // direct it at a fresh path and atomically rename over the target.
    let mut tmp: PathBuf = target.to_path_buf();
    tmp.set_extension(format!(
        "{}.merge.tmp",
        target
            .extension()
            .map(|e| e.to_string_lossy().into_owned())
            .unwrap_or_else(|| "csv".into())
    ));
    let status = Command::new(merge_script)
        .arg(&tmp)
        .arg(target)
        .arg(new_csv)
        .status()
        .with_context(|| format!("invoke {}", merge_script.display()))?;
    if !status.success() {
        // Leave the tmp file in place so the user can inspect it.
        bail!(
            "{} exited with status {:?}; tmp file left at {}",
            merge_script.display(),
            status.code(),
            tmp.display()
        );
    }
    fs::rename(&tmp, target).with_context(|| {
        format!("rename {} → {}", tmp.display(), target.display())
    })?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{NaiveDate, NaiveDateTime};
    use std::io::Read;

    fn rec(dt: NaiveDateTime, sys: u16, dia: u16, pulse: u16) -> Record {
        Record { datetime: dt, sys, dia, pulse, mov: 0, ihb: 0 }
    }

    #[test]
    fn header_has_17_columns_and_starts_with_fecha_hora() {
        assert_eq!(HEADER.matches(',').count(), 16, "header should have 17 cols");
        assert!(HEADER.starts_with("Fecha,Hora,Sistólica"));
        assert!(HEADER.ends_with(",Dispositivo,Notas"));
    }

    #[test]
    fn date_format_matches_existing_input() {
        let dt = NaiveDate::from_ymd_opt(2026, 5, 20)
            .unwrap()
            .and_hms_opt(8, 53, 0)
            .unwrap();
        let r = rec(dt, 109, 62, 77);
        assert_eq!(format_date_es(&r), "20 may. 2026");
        assert_eq!(format_time(&r), "08:53");
    }

    #[test]
    fn written_row_has_17_columns() {
        let dt = NaiveDate::from_ymd_opt(2026, 5, 20)
            .unwrap()
            .and_hms_opt(8, 53, 0)
            .unwrap();
        let r = rec(dt, 109, 62, 77);
        let mut buf: Vec<u8> = Vec::new();
        write_row(&mut buf, &r).unwrap();
        let line = std::str::from_utf8(&buf).unwrap().trim_end();
        assert_eq!(line.matches(',').count(), 16, "expected 17 cols, got line: {line}");
        assert!(line.starts_with("20 may. 2026,08:53,109,62,77,"));
    }

    #[test]
    fn flatten_dedups_by_datetime() {
        let dt1 = NaiveDate::from_ymd_opt(2026, 5, 1).unwrap().and_hms_opt(8, 0, 0).unwrap();
        let dt2 = NaiveDate::from_ymd_opt(2026, 5, 2).unwrap().and_hms_opt(8, 0, 0).unwrap();
        let users = vec![
            vec![rec(dt2, 110, 70, 70), rec(dt1, 100, 60, 60)],
            vec![rec(dt1, 101, 61, 61)],
        ];
        let flat = flatten_users(users);
        assert_eq!(flat.len(), 2);
        assert_eq!(flat[0].datetime, dt1);
        assert_eq!(flat[1].datetime, dt2);
    }

    #[test]
    fn merge_into_copies_when_target_missing() {
        let dir = tempdir_or_skip();
        let new = dir.join("new.csv");
        let target = dir.join("input.csv");
        let r = rec(
            NaiveDate::from_ymd_opt(2026, 5, 20).unwrap().and_hms_opt(8, 53, 0).unwrap(),
            120, 80, 65,
        );
        write_records(&new, &[r]).unwrap();
        let fake_merge_script = dir.join("never_run.sh"); // not invoked
        merge_into(&target, &new, &fake_merge_script).unwrap();
        let mut contents = String::new();
        fs::File::open(&target).unwrap().read_to_string(&mut contents).unwrap();
        assert!(contents.starts_with(HEADER));
    }

    fn tempdir_or_skip() -> std::path::PathBuf {
        let p = std::env::temp_dir().join(format!("omblepy-rs-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&p);
        fs::create_dir_all(&p).unwrap();
        p
    }
}
