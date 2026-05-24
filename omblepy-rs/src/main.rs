use std::time::Duration;

use anyhow::{Context, Result, bail};
use clap::{Parser, Subcommand};

mod ble;
mod devices;
mod protocol;

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
            if !devices::is_supported(&device) {
                bail!("unsupported device '{}', run `list-devices` to see options", device);
            }
            let key = match key {
                Some(s) => protocol::parse_pairing_key(&s)?,
                None => protocol::DEFAULT_PAIRING_KEY,
            };
            let cfg = devices::channel_config_for(&device);
            let ble = ble::Ble::new().await?;
            let addr = ble::parse_mac(&mac)?;
            let dev = ble.connect(addr).await.context("connect to meter")?;
            ble.wait_for_service(&dev, cfg.parent_service, 20).await?;
            let mut proto = protocol::Protocol::new(&dev, cfg).await?;
            proto.write_pairing_key(&key).await?;
            // Upstream omblepy does a start+end transmission after a fresh
            // pair to settle the device; mirror that.
            proto.start_transmission().await?;
            proto.end_transmission().await?;
            println!("Paired {mac} as {device}. You can now drop the --pair flag.");
        }
    }
    Ok(())
}
