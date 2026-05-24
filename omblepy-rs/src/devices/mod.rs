// Registry of supported Omron device-driver names. Each name resolves to a
// `DeviceDriver` impl in a later commit; for now it's a static list so the
// `list-devices` CLI works.

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
