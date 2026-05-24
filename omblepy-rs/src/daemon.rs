//! Listener daemon.
//!
//! Omron meters don't keep a connection open — they advertise when the BT
//! button is pressed, accept one transmission, then sleep.  So "listener
//! mode" here is a scan-and-pull loop:
//!
//! ```text
//! discover_devices → wait for target MAC's advertisement
//!   → connect → unlock → read --new-rec-only → write csv
//!   → merge into /data/input.csv via omron_merge.sh
//!   → rebuild the report (analyze.py + make_report.sh)
//!   → disconnect → resume scanning
//! ```
//!
//! Per-iteration errors are logged and the loop continues — a dropped
//! Bluetooth packet or a transient DBus glitch should not take the daemon
//! down.  SIGINT / SIGTERM break the loop cleanly.

use std::path::PathBuf;
use std::process::Stdio;
use std::time::Duration;

use anyhow::{Context, Result, anyhow};
use bluer::{AdapterEvent, Address};
use futures::StreamExt;
use tokio::process::Command;
use tokio::time::{Instant, MissedTickBehavior, interval};
use tracing::{error, info, warn};

use crate::ble::Ble;
use crate::csv_out::{flatten_users, merge_into, write_records};
use crate::devices;
use crate::protocol::Protocol;
use crate::shared::read_records;

pub struct DaemonConfig {
    pub device_name: String,
    pub mac: Address,
    pub pairing_key: [u8; 16],
    pub session_csv: PathBuf,
    pub merge_target: PathBuf,
    pub merge_script: PathBuf,
    pub rebuild_cmd: Option<String>,
    pub time_sync_each_session: bool,
}

pub async fn run(cfg: DaemonConfig) -> Result<()> {
    let driver = devices::driver_for(&cfg.device_name).ok_or_else(|| {
        anyhow!(
            "unknown device '{}', run `list-devices` to see options",
            cfg.device_name
        )
    })?;
    let channel = driver.channel_config();
    let ble = Ble::new().await?;

    let shutdown = wait_for_shutdown_signal();
    tokio::pin!(shutdown);

    info!(
        "omblepy-rs daemon online — device={} mac={} merge_target={}",
        cfg.device_name,
        cfg.mac,
        cfg.merge_target.display()
    );

    loop {
        tokio::select! {
            biased;
            _ = &mut shutdown => {
                info!("daemon: shutdown signal received, exiting");
                return Ok(());
            }
            result = wait_for_target_advertisement(&ble, cfg.mac) => {
                match result {
                    Ok(()) => {}
                    Err(e) => {
                        error!("daemon: scan failed: {e:?}");
                        tokio::time::sleep(Duration::from_secs(10)).await;
                        continue;
                    }
                }
            }
        }

        info!("daemon: meter advertisement seen, starting session");
        match run_session(&ble, &*driver, &channel, &cfg).await {
            Ok(true) => {
                if let Some(cmd) = &cfg.rebuild_cmd {
                    if let Err(e) = run_rebuild(cmd).await {
                        error!("daemon: rebuild command failed: {e:?}");
                    }
                }
            }
            Ok(false) => info!("daemon: no new records this session"),
            Err(e) => {
                error!("daemon: session failed: {e:?}");
            }
        }

        // Short cool-down before re-scanning so we don't immediately latch
        // onto the same advertisement burst.
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}

async fn wait_for_target_advertisement(ble: &Ble, target: Address) -> Result<()> {
    let mut events = ble
        .adapter
        .discover_devices()
        .await
        .context("start discovery")?;

    let mut heartbeat = interval(Duration::from_secs(60));
    heartbeat.set_missed_tick_behavior(MissedTickBehavior::Skip);
    heartbeat.tick().await; // consume the immediate first tick
    let started = Instant::now();

    loop {
        tokio::select! {
            biased;
            ev = events.next() => {
                match ev {
                    Some(AdapterEvent::DeviceAdded(addr)) if addr == target => return Ok(()),
                    Some(AdapterEvent::DeviceAdded(_)) => continue,
                    Some(_) => continue,
                    None => return Err(anyhow!("discovery stream ended unexpectedly")),
                }
            }
            _ = heartbeat.tick() => {
                let elapsed = started.elapsed().as_secs();
                info!("daemon: still scanning ({elapsed}s)…");
            }
        }
    }
}

/// Returns `true` when at least one new record was pulled and merged.
async fn run_session(
    ble: &Ble,
    driver: &dyn crate::shared::DeviceDriver,
    channel: &crate::protocol::ChannelConfig,
    cfg: &DaemonConfig,
) -> Result<bool> {
    let dev = ble.connect(cfg.mac).await.context("connect to meter")?;
    ble.wait_for_service(&dev, channel.parent_service, 20).await?;
    let mut proto = Protocol::new(&dev, channel.clone()).await?;
    let users = read_records(
        &mut proto,
        driver,
        &cfg.pairing_key,
        /* new-rec-only = */ true,
        cfg.time_sync_each_session,
    )
    .await
    .context("read records from meter")?;
    // Be polite and explicitly disconnect — bluer drops the link on Device
    // drop, but a deliberate disconnect lets the meter return to sleep
    // immediately rather than sitting at the GATT-idle timeout.
    if let Err(e) = dev.disconnect().await {
        warn!("daemon: disconnect returned {e:?} (continuing)");
    }
    let total: usize = users.iter().map(|u| u.len()).sum();
    if total == 0 {
        return Ok(false);
    }
    let flat = flatten_users(users);
    write_records(&cfg.session_csv, &flat)?;
    merge_into(&cfg.merge_target, &cfg.session_csv, &cfg.merge_script).with_context(|| {
        format!("merge {} into {}", cfg.session_csv.display(), cfg.merge_target.display())
    })?;
    info!(
        "daemon: pulled {} record(s), merged into {}",
        total,
        cfg.merge_target.display()
    );
    Ok(true)
}

async fn run_rebuild(cmd: &str) -> Result<()> {
    info!("daemon: rebuilding report via `{cmd}`");
    let status = Command::new("sh")
        .arg("-c")
        .arg(cmd)
        .stdin(Stdio::null())
        .status()
        .await
        .context("spawn rebuild shell")?;
    if !status.success() {
        return Err(anyhow!("rebuild exited with status {:?}", status.code()));
    }
    info!("daemon: report rebuilt");
    Ok(())
}

#[cfg(unix)]
async fn wait_for_shutdown_signal() {
    use tokio::signal::unix::{SignalKind, signal};
    let mut term = match signal(SignalKind::terminate()) {
        Ok(s) => s,
        Err(e) => {
            warn!("daemon: cannot install SIGTERM handler: {e}");
            return;
        }
    };
    let mut int = match signal(SignalKind::interrupt()) {
        Ok(s) => s,
        Err(e) => {
            warn!("daemon: cannot install SIGINT handler: {e}");
            return;
        }
    };
    tokio::select! {
        _ = term.recv() => {}
        _ = int.recv() => {}
    }
}

#[cfg(not(unix))]
async fn wait_for_shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
}
