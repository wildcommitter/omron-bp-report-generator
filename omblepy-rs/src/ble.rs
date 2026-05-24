//! Thin async wrapper around bluer for the operations omblepy-rs needs.
//!
//! Mirrors what `bleak.BleakScanner` / `BleakClient` give the Python tool:
//! adapter access, a time-boxed scan that returns a list of advertisements,
//! and a `connect` helper that resolves the Omron parent service before
//! returning.
use std::collections::HashMap;
use std::time::Duration;

use anyhow::{Context, Result, anyhow};
use bluer::{Adapter, AdapterEvent, Address, Device, Session};
use futures::StreamExt;
use tokio::time::timeout;

pub struct Ble {
    pub adapter: Adapter,
    _session: Session,
}

#[derive(Debug, Clone)]
pub struct Discovered {
    pub address: Address,
    pub name: Option<String>,
    pub rssi: Option<i16>,
}

impl Ble {
    pub async fn new() -> Result<Self> {
        let session = Session::new().await.context("connect to bluez over dbus")?;
        let adapter = session
            .default_adapter()
            .await
            .context("get default bluetooth adapter")?;
        adapter
            .set_powered(true)
            .await
            .context("power on bluetooth adapter")?;
        Ok(Self {
            adapter,
            _session: session,
        })
    }

    /// Scan for nearby advertisements for `dur` seconds. Returns one entry per
    /// MAC, sorted by RSSI (strongest first).
    pub async fn scan(&self, dur: Duration) -> Result<Vec<Discovered>> {
        let mut events = self
            .adapter
            .discover_devices()
            .await
            .context("start discovery")?;
        let mut seen: HashMap<Address, Discovered> = HashMap::new();

        let collect = async {
            while let Some(ev) = events.next().await {
                if let AdapterEvent::DeviceAdded(addr) = ev {
                    if let Ok(dev) = self.adapter.device(addr) {
                        let name = dev.name().await.ok().flatten();
                        let rssi = dev.rssi().await.ok().flatten();
                        seen.insert(addr, Discovered { address: addr, name, rssi });
                    }
                }
            }
        };
        let _ = timeout(dur, collect).await;

        let mut out: Vec<Discovered> = seen.into_values().collect();
        out.sort_by(|a, b| b.rssi.unwrap_or(i16::MIN).cmp(&a.rssi.unwrap_or(i16::MIN)));
        Ok(out)
    }

    /// Connect to a device by MAC address and return the `Device` handle.
    pub async fn connect(&self, addr: Address) -> Result<Device> {
        let dev = self
            .adapter
            .device(addr)
            .with_context(|| format!("look up device {addr}"))?;
        if !dev.is_connected().await.unwrap_or(false) {
            dev.connect()
                .await
                .with_context(|| format!("connect to {addr}"))?;
        }
        Ok(dev)
    }

    /// Wait until the device exposes `service_uuid`, polling every 250ms.
    /// Mirrors the 20-iteration / 0.25s wait in omblepy.py's `main()`.
    pub async fn wait_for_service(
        &self,
        dev: &Device,
        service_uuid: bluer::Uuid,
        attempts: usize,
    ) -> Result<()> {
        for _ in 0..attempts {
            let uuids = dev.uuids().await.ok().flatten().unwrap_or_default();
            if uuids.contains(&service_uuid) {
                return Ok(());
            }
            tokio::time::sleep(Duration::from_millis(250)).await;
        }
        Err(anyhow!(
            "required service {service_uuid} not exposed by device {}",
            dev.address()
        ))
    }
}

/// Parse a `XX:XX:XX:XX:XX:XX` MAC string into a bluer Address.
pub fn parse_mac(s: &str) -> Result<Address> {
    s.parse::<Address>()
        .with_context(|| format!("invalid bluetooth address: {s}"))
}
