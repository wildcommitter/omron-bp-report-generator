use clap::{Parser, Subcommand};

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
}

fn main() {
    let cli = Cli::parse();
    match cli.cmd {
        Cmd::ListDevices => {
            for name in devices::supported_names() {
                println!("{name}");
            }
        }
    }
}
