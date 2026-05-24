// Registry of supported Omron device-driver names. Each name resolves to a
// `DeviceDriver` impl in a later commit; for now it's a static list so the
// `list-devices` CLI works and a `channel_config_for` shim so pair/scan know
// the BLE layout to expect.

use crate::protocol::ChannelConfig;

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

/// Return the BLE channel layout for a device. Every supported model except
/// HEM-7380T1 uses the legacy 4-channel protocol with the default service
/// UUIDs; the 7380T1 override lands in commit 8.
pub fn channel_config_for(_name: &str) -> ChannelConfig {
    ChannelConfig::default()
}
