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
use std::sync::OnceLock;

use anyhow::{Context, Result, anyhow};
use serde::Deserialize;
use tracing::warn;

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

/// Environment variable that points at a user-supplied JSON file with
/// the same schema as the embedded catalogue.  Entries from the external
/// file override entries with the same canonical name; entirely new
/// models extend the catalogue.  Mirrors ubpm's `JSON_EXT` pattern.
pub const OVERRIDE_ENV: &str = "OMBLEPY_DEVICES_JSON";

/// The embedded catalogue from ubpm's `omron-bluetooth.json`, accessible
/// without disk I/O.  Internal — call `catalogue()` for the merged view.
pub fn embedded() -> Result<HashMap<String, DeviceSpec>> {
    parse_catalogue(EMBEDDED_CATALOGUE)
}

/// Merged embedded + external (from `$OMBLEPY_DEVICES_JSON`) catalogue,
/// parsed once and cached for the lifetime of the process.
pub fn catalogue() -> &'static HashMap<String, DeviceSpec> {
    static CATALOGUE: OnceLock<HashMap<String, DeviceSpec>> = OnceLock::new();
    CATALOGUE.get_or_init(|| {
        let mut cat = parse_catalogue(EMBEDDED_CATALOGUE)
            .expect("embedded devices.json is well-formed");
        if let Ok(path) = std::env::var(OVERRIDE_ENV) {
            match std::fs::read_to_string(&path) {
                Ok(text) => match parse_catalogue(&text) {
                    Ok(ext) => {
                        let n = ext.len();
                        for (k, v) in ext {
                            cat.insert(k, v);
                        }
                        tracing::info!(
                            "loaded {n} device entries from {OVERRIDE_ENV}={path}"
                        );
                    }
                    Err(e) => warn!("ignoring {OVERRIDE_ENV}={path}: parse error: {e:?}"),
                },
                Err(e) => warn!("ignoring {OVERRIDE_ENV}={path}: read error: {e}"),
            }
        }
        cat
    })
}

/// Look up a device by name in the merged catalogue.
pub fn lookup(name: &str) -> Result<DeviceSpec> {
    let key = canonical_name(name);
    catalogue()
        .get(&key)
        .cloned()
        .ok_or_else(|| anyhow!("unsupported device '{name}' — run `list-devices` for the catalogue"))
}

/// Names known to the merged catalogue, sorted for stable output.
pub fn known_names() -> Vec<String> {
    let mut names: Vec<String> = catalogue().values().map(|s| s.model.clone()).collect();
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

    #[test]
    fn external_catalogue_merges_with_embedded() {
        // The merge logic itself — same shape both sides, external wins
        // on name conflicts, novel entries extend the map.  Mirrors what
        // `catalogue()` does at runtime when $OMBLEPY_DEVICES_JSON is set.
        let mut combined = parse_catalogue(EMBEDDED_CATALOGUE).unwrap();
        let external = r#"[
          {
            "model"     : "HEM-7361T",
            "alias"     : "user override",
            "helper"    : "test",
            "user"      : 1,
            "memory"    : 50,
            "addr1"     : "0xBEEF",
            "addr2"     : "0xBEEF",
            "step"      : 16,
            "bigendian" : false,
            "pairing"   : true,
            "uuid"      : "ecbe3980-c9a2-11e1-b1bd-0002a5d5c51b",
            "data": {
              "year":{"byte":3,"bit":0,"len":6},"month":{"byte":4,"bit":10,"len":4},
              "day":{"byte":4,"bit":5,"len":5},"hour":{"byte":4,"bit":0,"len":5},
              "minute":{"byte":6,"bit":6,"len":6},"second":{"byte":6,"bit":0,"len":6},
              "sys":{"byte":0,"bit":0,"len":8},"dia":{"byte":1,"bit":0,"len":8},
              "bpm":{"byte":2,"bit":0,"len":8},"ihb":{"byte":4,"bit":14,"len":1},
              "mov":{"byte":4,"bit":15,"len":1}
            }
          },
          {
            "model"     : "HEM-CUSTOM-X",
            "alias"     : "user-added model",
            "helper"    : "test",
            "user"      : 1,
            "memory"    : 25,
            "addr1"     : "0x0100",
            "addr2"     : "0x0100",
            "step"      : 16,
            "bigendian" : false,
            "pairing"   : true,
            "uuid"      : "ecbe3980-c9a2-11e1-b1bd-0002a5d5c51b",
            "data": {
              "year":{"byte":3,"bit":0,"len":6},"month":{"byte":4,"bit":10,"len":4},
              "day":{"byte":4,"bit":5,"len":5},"hour":{"byte":4,"bit":0,"len":5},
              "minute":{"byte":6,"bit":6,"len":6},"second":{"byte":6,"bit":0,"len":6},
              "sys":{"byte":0,"bit":0,"len":8},"dia":{"byte":1,"bit":0,"len":8},
              "bpm":{"byte":2,"bit":0,"len":8},"ihb":{"byte":4,"bit":14,"len":1},
              "mov":{"byte":4,"bit":15,"len":1}
            }
          }
        ]"#;
        let ext = parse_catalogue(external).unwrap();
        for (k, v) in ext {
            combined.insert(k, v);
        }
        // Embedded 7361T was memory=100; external wins with memory=50.
        assert_eq!(combined.get("hem-7361t").unwrap().memory, 50);
        // Embedded entries unrelated to the override are untouched.
        assert_eq!(combined.get("hem-7530t").unwrap().memory, 90);
        // Novel entry made it in.
        assert!(combined.contains_key("hem-custom-x"));
    }
}
