use std::time::Duration;

use anyhow::Result;
use clap::{Parser, Subcommand};

mod ble;
mod devices;

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
    }
    Ok(())
}
