//! Thin async wrapper around bluer for the operations omblepy-rs needs.
//!
//! Mirrors what `bleak.BleakScanner` / `BleakClient` give the Python tool:
//! adapter access, a time-boxed scan that returns a list of advertisements,
//! and a `connect` helper that resolves the Omron parent service before
//! returning.
use std::collections::HashMap;
use std::time::Duration;

use anyhow::{Context, Result, anyhow, bail};
use bluer::{Adapter, AdapterEvent, Address, Device, Session};
use futures::StreamExt;
use tokio::time::timeout;
use tracing::info;

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

    /// Discover `target` via a brief scan so BlueZ's object cache catches
    /// the advertisement. Returns as soon as the target is seen, or errors
    /// after `dur` if it isn't.
    pub async fn discover(&self, target: Address, dur: Duration) -> Result<()> {
        let mut events = self
            .adapter
            .discover_devices()
            .await
            .context("start discovery")?;
        let wait = async {
            while let Some(ev) = events.next().await {
                if let AdapterEvent::DeviceAdded(addr) = ev {
                    if addr == target {
                        return Ok::<(), anyhow::Error>(());
                    }
                }
            }
            bail!("discovery stream ended before {target} was seen")
        };
        match timeout(dur, wait).await {
            Ok(Ok(())) => Ok(()),
            Ok(Err(e)) => Err(e),
            Err(_) => Err(anyhow!(
                "device {target} did not advertise within {} seconds — \
                 is bluetooth enabled on the meter? (press the BT button)",
                dur.as_secs()
            )),
        }
    }

    /// Connect to a device by MAC address and return the `Device` handle.
    /// `adapter.device(addr)` returns a proxy even for MACs BlueZ has never
    /// seen, so a subsequent `.connect()` errors with "target object not
    /// present or removed" — we run a brief discovery first so BlueZ
    /// actually catches the advertisement.  Cached / currently-advertising
    /// devices resolve in milliseconds because `discover_devices()`
    /// re-emits `DeviceAdded` for known entries.
    pub async fn connect(&self, addr: Address) -> Result<Device> {
        info!("looking for {addr} on the air…");
        self.discover(addr, Duration::from_secs(15)).await?;
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

    /// Wait until the device exposes `service_uuid` via GATT.  Two stages:
    ///
    /// 1. Wait for BlueZ's `ServicesResolved` property to flip true — that
    ///    happens once the post-connect GATT discovery finishes.  Calling
    ///    `services()` before this point returns an empty list even though
    ///    the peripheral does expose the services.
    /// 2. Walk the resolved primary services and look for `service_uuid`.
    ///
    /// Polls at 250 ms; `attempts` is the upper bound for both stages
    /// combined.
    pub async fn wait_for_service(
        &self,
        dev: &Device,
        service_uuid: bluer::Uuid,
        attempts: usize,
    ) -> Result<()> {
        let mut resolved = false;
        for _ in 0..attempts {
            if dev.is_services_resolved().await.unwrap_or(false) {
                resolved = true;
                break;
            }
            tokio::time::sleep(Duration::from_millis(250)).await;
        }
        if !resolved {
            tracing::warn!(
                "{}: ServicesResolved never became true — checking services anyway",
                dev.address()
            );
        }
        let mut last_seen: Vec<bluer::Uuid> = Vec::new();
        for _ in 0..attempts {
            if let Ok(services) = dev.services().await {
                last_seen.clear();
                for s in services {
                    if let Ok(u) = s.uuid().await {
                        last_seen.push(u);
                        if u == service_uuid {
                            return Ok(());
                        }
                    }
                }
            }
            tokio::time::sleep(Duration::from_millis(250)).await;
        }
        Err(anyhow!(
            "required service {service_uuid} not exposed by device {} \
             (services discovered: {:?})",
            dev.address(),
            last_seen
        ))
    }
}

/// Parse a `XX:XX:XX:XX:XX:XX` MAC string into a bluer Address.
pub fn parse_mac(s: &str) -> Result<Address> {
    s.parse::<Address>()
        .with_context(|| format!("invalid bluetooth address: {s}"))
}
