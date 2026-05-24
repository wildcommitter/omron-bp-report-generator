// Registry of supported Omron device-driver instances. Each name resolves
// to a boxed `DeviceDriver` impl from a sibling module.

use crate::protocol::ChannelConfig;
use crate::shared::DeviceDriver;

pub mod common;
mod hem_6232t;
mod hem_7150t;
mod hem_7155t;
mod hem_7322t;
mod hem_7342t;
mod hem_7361t;
mod hem_7530t;
mod hem_7600t;

pub const SUPPORTED: &[&str] = &[
    "hem-6232t",
    "hem-7150t",
    "hem-7155t",
    "hem-7322t",
    "hem-7342t",
    "hem-7361t",
    "hem-7380t1",
    "hem-7530t",
    "hem-7600t",
];

pub fn supported_names() -> impl Iterator<Item = &'static str> {
    SUPPORTED.iter().copied()
}

pub fn is_supported(name: &str) -> bool {
    SUPPORTED.iter().any(|n| n.eq_ignore_ascii_case(name))
}

/// Look up a device by name and return its driver as a trait object.
/// Returns None for names that are listed as supported but not yet
/// implemented (they will be added in later commits).
pub fn driver_for(name: &str) -> Option<Box<dyn DeviceDriver>> {
    match name.to_ascii_lowercase().as_str() {
        "hem-6232t" => Some(Box::new(hem_6232t::Hem6232t)),
        "hem-7150t" => Some(Box::new(hem_7150t::Hem7150t)),
        "hem-7155t" => Some(Box::new(hem_7155t::Hem7155t)),
        "hem-7322t" => Some(Box::new(hem_7322t::Hem7322t)),
        "hem-7342t" => Some(Box::new(hem_7342t::Hem7342t)),
        "hem-7361t" => Some(Box::new(hem_7361t::Hem7361t)),
        "hem-7530t" => Some(Box::new(hem_7530t::Hem7530t)),
        "hem-7600t" => Some(Box::new(hem_7600t::Hem7600t)),
        _ => None,
    }
}

/// Return the BLE channel layout for a device. Falls back to the legacy
/// 4-channel layout when the device hasn't overridden it.
pub fn channel_config_for(name: &str) -> ChannelConfig {
    driver_for(name)
        .map(|d| d.channel_config())
        .unwrap_or_default()
}
