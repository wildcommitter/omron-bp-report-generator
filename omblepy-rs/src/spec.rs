//! Device-spec catalogue, sourced from
//! `ubpm/sources/plugins/vendor/omron/bluetooth/omron-bluetooth.json`
//! and embedded at compile time as `devices.json`.
//!
//! Each catalogue entry describes one Omron model: its addressing,
//! BLE service UUID, endianness, pairing requirement, and the
//! byte/bit/len triples used to decode a single 8-byte record's
//! sys / dia / bpm / date / flags fields.  Time-sync isn't covered
//! here — the JSON doesn't carry it; we keep a separate Rust-side
//! lookup keyed by the device family.

use std::collections::HashMap;

use anyhow::{Context, Result, anyhow};
use serde::Deserialize;

/// One field's bit slot inside the 8-byte parsed record.
#[derive(Debug, Clone, Copy, Deserialize)]
pub struct FieldSpec {
    pub byte: usize,
    pub bit: usize,
    pub len: usize,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DataSpec {
    pub year: FieldSpec,
    pub month: FieldSpec,
    pub day: FieldSpec,
    pub hour: FieldSpec,
    pub minute: FieldSpec,
    pub second: FieldSpec,
    pub sys: FieldSpec,
    pub dia: FieldSpec,
    pub bpm: FieldSpec,
    pub ihb: FieldSpec,
    pub mov: FieldSpec,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DeviceSpec {
    pub model: String,
    #[serde(default)]
    pub alias: String,
    /// Number of users on the meter (1 or 2).
    pub user: u8,
    /// Records-per-user the meter stores.
    pub memory: u16,
    #[serde(deserialize_with = "hex_u16")]
    pub addr1: u16,
    #[serde(deserialize_with = "hex_u16")]
    pub addr2: u16,
    /// EEPROM address increment per record (== record byte size on the wire).
    pub step: u8,
    /// Big-endian record-byte ordering — pairwise swap before bit-slicing.
    pub bigendian: bool,
    /// Requires writing an in-band pairing key (omblepy / ubpm style).
    pub pairing: bool,
    pub uuid: String,
    pub data: DataSpec,
}

fn hex_u16<'de, D>(d: D) -> std::result::Result<u16, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let s: String = Deserialize::deserialize(d)?;
    let s = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X")).unwrap_or(&s);
    u16::from_str_radix(s, 16).map_err(serde::de::Error::custom)
}

/// Canonicalise a device name for lookup: lowercase, drop variant
/// suffixes like " (V2)" so users can write `hem-7155t-v2` and find it.
pub fn canonical_name(name: &str) -> String {
    name.to_ascii_lowercase()
        .replace(' ', "")
        .replace("(v", "-v")
        .replace(')', "")
}

const EMBEDDED_CATALOGUE: &str = include_str!("../devices.json");

/// Parse a catalogue (JSON array of DeviceSpecs) into a name-keyed map.
pub fn parse_catalogue(json: &str) -> Result<HashMap<String, DeviceSpec>> {
    let list: Vec<DeviceSpec> = serde_json::from_str(json).context("parse devices.json")?;
    let mut by_name = HashMap::with_capacity(list.len());
    for spec in list {
        by_name.insert(canonical_name(&spec.model), spec);
    }
    Ok(by_name)
}

/// The embedded catalogue from ubpm's `omron-bluetooth.json`, accessible
/// without disk I/O.  Used as the default device source by `lookup`.
pub fn embedded() -> Result<HashMap<String, DeviceSpec>> {
    parse_catalogue(EMBEDDED_CATALOGUE)
}

/// Look up a device by name in the embedded catalogue.
pub fn lookup(name: &str) -> Result<DeviceSpec> {
    let cat = embedded()?;
    let key = canonical_name(name);
    cat.get(&key)
        .cloned()
        .ok_or_else(|| anyhow!("unsupported device '{name}' — run `list-devices` for the catalogue"))
}

/// Names known to the embedded catalogue, sorted for stable output.
pub fn known_names() -> Vec<String> {
    let mut names: Vec<String> = embedded()
        .map(|c| c.into_values().map(|s| s.model).collect())
        .unwrap_or_default();
    names.sort();
    names
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedded_catalogue_parses() {
        let cat = embedded().expect("embedded JSON must be valid");
        assert!(cat.len() >= 9, "expected at least 9 models, got {}", cat.len());
        // Spot-check a few known entries (model strings canonicalised).
        assert!(cat.contains_key("hem-7361t"));
        assert!(cat.contains_key("hem-7530t"));
        assert!(cat.contains_key("hem-7380t"));
    }

    #[test]
    fn hex_u16_decodes_with_prefix() {
        let spec = lookup("HEM-7530T").unwrap();
        assert_eq!(spec.addr1, 0x02E8);
        assert_eq!(spec.memory, 90);
        assert!(spec.bigendian);
        assert!(spec.pairing);
    }

    #[test]
    fn variant_names_are_resolvable() {
        // HEM-7155T (V2) and (V3) live in the JSON alongside the base entry —
        // canonical_name() drops the parens so they're addressable as
        // hem-7155t-v2 and hem-7155t-v3.
        let cat = embedded().unwrap();
        assert!(cat.contains_key("hem-7155t"));
        assert!(cat.contains_key("hem-7155t-v2"));
        assert!(cat.contains_key("hem-7155t-v3"));
    }

    #[test]
    fn parse_rejects_malformed_json() {
        let err = parse_catalogue("{ not valid }").unwrap_err();
        assert!(format!("{err:?}").contains("parse devices.json"));
    }
}
