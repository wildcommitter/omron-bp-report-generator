use std::path::PathBuf;
use std::time::Duration;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};

mod ble;
mod csv_out;
mod daemon;
mod devices;
mod protocol;
mod shared;

#[derive(Parser, Debug)]
#[command(
    name = "omblepy-rs",
    version,
    about = "Rust port of omblepy — reads records from Omron BLE blood-pressure monitors."
)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand, Debug)]
enum Cmd {
    /// List the device models the binary knows how to talk to.
    ListDevices,
    /// Scan for nearby BLE devices and print them sorted by signal strength.
    Scan {
        /// Seconds to keep the radio in discovery mode.
        #[arg(long, default_value_t = 6)]
        seconds: u64,
    },
    /// Program the pairing key into a device that's currently in pairing
    /// mode. Run this once per meter; subsequent reads use plain `unlock`
    /// behind the scenes.
    Pair {
        /// Device model (e.g. hem-7361t). Determines BLE channel layout.
        #[arg(long, short = 'd')]
        device: String,
        /// Bluetooth MAC address of the meter (XX:XX:XX:XX:XX:XX).
        #[arg(long, short = 'm')]
        mac: String,
        /// Override the 32-char-hex pairing key. Defaults to upstream
        /// omblepy's `deadbeaf…` so devices paired with the Python tool
        /// keep working.
        #[arg(long, short = 'k')]
        key: Option<String>,
    },
    /// Stay running, watch for the meter to advertise, and pull-merge-
    /// rebuild on every BT-button press.  See daemon.rs for the loop.
    Daemon {
        #[arg(long, short = 'd')]
        device: String,
        #[arg(long, short = 'm')]
        mac: String,
        /// Existing input.csv to merge each session into.
        #[arg(long, default_value = "/data/input.csv")]
        merge_target: PathBuf,
        /// Per-session staging CSV (overwritten every iteration).
        #[arg(long, default_value = "/tmp/omblepy-session.csv")]
        session_csv: PathBuf,
        #[arg(long, default_value = "/app/omron_merge.sh")]
        merge_script: PathBuf,
        /// Shell command run after each merge.  Typically rebuilds the
        /// report — e.g. `python /app/analyze.py && /app/make_report.sh`.
        #[arg(long)]
        rebuild_cmd: Option<String>,
        /// Override the 32-char-hex pairing key.
        #[arg(long, short = 'k')]
        key: Option<String>,
        /// Sync the meter's clock on every session.  Off by default —
        /// once per power-cycle is plenty.
        #[arg(long)]
        time_sync: bool,
    },
    /// One-shot read: connect to a paired meter, pull records, write a
    /// CSV in OMRON-Complete schema that bp_utils.load_omron_csv() reads.
    Dump {
        #[arg(long, short = 'd')]
        device: String,
        #[arg(long, short = 'm')]
        mac: String,
        /// Output CSV path. Defaults to ./omblepy.csv next to cwd.
        #[arg(long, short = 'o', default_value = "omblepy.csv")]
        output: PathBuf,
        /// Merge the freshly-pulled session into this existing CSV via
        /// omron_merge.sh, deduplicating on (Fecha,Hora). Typical use:
        /// `--merge-into /data/input.csv`.
        #[arg(long)]
        merge_into: Option<PathBuf>,
        /// Path to omron_merge.sh. Defaults to the container layout.
        #[arg(long, default_value = "/app/omron_merge.sh")]
        merge_script: PathBuf,
        /// Only fetch records flagged as unread (and clear the counter
        /// on the device). Otherwise read all 100 slots per user.
        #[arg(long, short = 'n')]
        new_rec_only: bool,
        /// Sync the meter's clock with the host's local time.
        #[arg(long, short = 't')]
        time_sync: bool,
        /// Override the 32-char-hex pairing key.
        #[arg(long, short = 'k')]
        key: Option<String>,
    },
}

fn init_logging() {
    let env = tracing_subscriber::EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));
    tracing_subscriber::fmt().with_env_filter(env).init();
}

#[tokio::main]
async fn main() -> Result<()> {
    init_logging();
    let cli = Cli::parse();
    match cli.cmd {
        Cmd::ListDevices => {
            for name in devices::supported_names() {
                println!("{name}");
            }
        }
        Cmd::Scan { seconds } => {
            let ble = ble::Ble::new().await?;
            let found = ble.scan(Duration::from_secs(seconds)).await?;
            println!("{:<3}  {:<17}  {:<5}  NAME", "ID", "MAC", "RSSI");
            for (i, d) in found.iter().enumerate() {
                let rssi = d
                    .rssi
                    .map(|r| r.to_string())
                    .unwrap_or_else(|| "-".to_string());
                let name = d.name.clone().unwrap_or_else(|| "<unknown>".to_string());
                println!("{:<3}  {}  {:<5}  {}", i, d.address, rssi, name);
            }
        }
        Cmd::Pair { device, mac, key } => {
            let driver = devices::driver_for(&device).ok_or_else(|| {
                anyhow::anyhow!("unsupported device '{}', run `list-devices` to see options", device)
            })?;
            let key = match key {
                Some(s) => protocol::parse_pairing_key(&s)?,
                None => protocol::DEFAULT_PAIRING_KEY,
            };
            let cfg = driver.channel_config();
            let ble = ble::Ble::new().await?;
            let addr = ble::parse_mac(&mac)?;
            let dev = ble.connect(addr).await.context("connect to meter")?;

            if driver.os_bonding_only() {
                dev.pair().await.context("OS-level BLE bond request")?;
                println!("Bonded {mac} as {device} via the OS.");
                return Ok(());
            }

            // 80 iterations × 250 ms = 20 s.  A freshly-bonded meter can take
            // ten-plus seconds to publish its GATT services through BlueZ; the
            // original 5 s budget was sometimes too tight.
            ble.wait_for_service(&dev, cfg.parent_service, 80).await?;
            let mut proto = protocol::Protocol::new(&dev, cfg).await?;
            proto.write_pairing_key(&key).await?;
            proto.start_transmission().await?;
            proto.end_transmission().await?;
            println!("Paired {mac} as {device}. You can now drop the --pair flag.");
        }
        Cmd::Dump {
            device,
            mac,
            output,
            merge_into,
            merge_script,
            new_rec_only,
            time_sync,
            key,
        } => {
            let driver = devices::driver_for(&device).ok_or_else(|| {
                anyhow::anyhow!("unsupported device '{}', run `list-devices` to see options", device)
            })?;
            let key = match key {
                Some(s) => protocol::parse_pairing_key(&s)?,
                None => protocol::DEFAULT_PAIRING_KEY,
            };
            let cfg = driver.channel_config();
            let ble = ble::Ble::new().await?;
            let addr = ble::parse_mac(&mac)?;
            let dev = ble.connect(addr).await.context("connect to meter")?;
            ble.wait_for_service(&dev, cfg.parent_service, 20).await?;
            let mut proto = protocol::Protocol::new(&dev, cfg).await?;
            let users = shared::read_records(&mut proto, &*driver, &key, new_rec_only, time_sync)
                .await
                .context("pull records from meter")?;
            let total: usize = users.iter().map(|u| u.len()).sum();
            let flat = csv_out::flatten_users(users);
            csv_out::write_records(&output, &flat)?;
            println!(
                "Wrote {} record(s) ({} after dedup) to {}",
                total,
                flat.len(),
                output.display()
            );
            if let Some(target) = merge_into {
                csv_out::merge_into(&target, &output, &merge_script).with_context(|| {
                    format!("merge into {}", target.display())
                })?;
                println!("Merged into {}", target.display());
            }
        }
        Cmd::Daemon {
            device,
            mac,
            merge_target,
            session_csv,
            merge_script,
            rebuild_cmd,
            key,
            time_sync,
        } => {
            let key = match key {
                Some(s) => protocol::parse_pairing_key(&s)?,
                None => protocol::DEFAULT_PAIRING_KEY,
            };
            let cfg = daemon::DaemonConfig {
                device_name: device,
                mac: ble::parse_mac(&mac)?,
                pairing_key: key,
                session_csv,
                merge_target,
                merge_script,
                rebuild_cmd,
                time_sync_each_session: time_sync,
            };
            daemon::run(cfg).await?;
        }
    }
    Ok(())
}
