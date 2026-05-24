//! Device registry, JSON-backed.
//!
//! Every model is described by a `DeviceSpec` in `devices.json` (the
//! verbatim ubpm catalogue, embedded at compile time).  `driver_for(name)`
//! instantiates a `GenericDriver` over the matching spec; no hand-rolled
//! per-device Rust files remain.

use crate::protocol::ChannelConfig;
use crate::shared::DeviceDriver;
use crate::spec;

pub mod common;
pub mod generic;

pub fn supported_names() -> Vec<String> {
    spec::known_names()
}

pub fn is_supported(name: &str) -> bool {
    spec::lookup(name).is_ok()
}

/// Look up a device by name and return its driver as a trait object.
pub fn driver_for(name: &str) -> Option<Box<dyn DeviceDriver>> {
    spec::lookup(name)
        .ok()
        .map(|s| Box::new(generic::GenericDriver::new(s)) as Box<dyn DeviceDriver>)
}

/// Return the BLE channel layout for a device.  Falls back to the legacy
/// 4-channel layout when the model isn't known.
pub fn channel_config_for(name: &str) -> ChannelConfig {
    driver_for(name)
        .map(|d| d.channel_config())
        .unwrap_or_default()
}
