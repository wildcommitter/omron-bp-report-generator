//! Omron BLE record-transfer protocol.
//!
//! Ports `bluetoothTxRxHandler` from upstream omblepy.py (lines 38–285).
//! Packets carry the same layout the Python code assembles:
//!
//! ```text
//!   size(1) | type(2) | addr(2) | data_len(1) | data(N) | pad(0x00) | xor_crc(1)
//! ```
//!
//! Total = N + 8 bytes. The XOR CRC is computed over the whole packet so the
//! receiver's XOR over every byte must be zero.
//!
//! On devices with four RX channels (the "legacy" Omron protocol) packets
//! larger than 16 bytes are split across consecutive 16-byte channels and
//! reassembled by `try_reassemble`. The HEM-7380T1 uses a single RX/TX
//! channel and the whole packet arrives in one notification.

use std::time::Duration;

use anyhow::{Context, Result, anyhow, bail};
use bluer::Device;
use bluer::Uuid;
use bluer::gatt::remote::Characteristic;
use futures::stream::{BoxStream, SelectAll, StreamExt, select_all};
use tokio::time::timeout;
use tracing::{debug, warn};

pub const LEGACY_PARENT_SERVICE_UUID: Uuid =
    Uuid::from_u128(0xecbe3980_c9a2_11e1_b1bd_0002a5d5c51b);
pub const LEGACY_UNLOCK_UUID: Uuid = Uuid::from_u128(0xb305b680_aee7_11e1_a730_0002a5d5c51b);
pub const LEGACY_RX_UUIDS: [Uuid; 4] = [
    Uuid::from_u128(0x49123040_aee8_11e1_a74d_0002a5d5c51b),
    Uuid::from_u128(0x4d0bf320_aee8_11e1_a0d9_0002a5d5c51b),
    Uuid::from_u128(0x5128ce60_aee8_11e1_b84b_0002a5d5c51b),
    Uuid::from_u128(0x560f1420_aee8_11e1_8184_0002a5d5c51b),
];
pub const LEGACY_TX_UUIDS: [Uuid; 4] = [
    Uuid::from_u128(0xdb5b55e0_aee7_11e1_965e_0002a5d5c51b),
    Uuid::from_u128(0xe0b8a060_aee7_11e1_92f4_0002a5d5c51b),
    Uuid::from_u128(0x0ae12b00_aee8_11e1_a192_0002a5d5c51b),
    Uuid::from_u128(0x10e1ba60_aee8_11e1_89e5_0002a5d5c51b),
];

/// Per-device BLE channel layout. The defaults match the four-channel
/// legacy protocol; HEM-7380T1 swaps in single-element vecs and a different
/// parent service UUID.
#[derive(Debug, Clone)]
pub struct ChannelConfig {
    pub parent_service: Uuid,
    pub rx_uuids: Vec<Uuid>,
    pub tx_uuids: Vec<Uuid>,
    pub unlock_uuid: Uuid,
    pub requires_unlock: bool,
    pub supports_pairing: bool,
}

impl Default for ChannelConfig {
    fn default() -> Self {
        Self {
            parent_service: LEGACY_PARENT_SERVICE_UUID,
            rx_uuids: LEGACY_RX_UUIDS.to_vec(),
            tx_uuids: LEGACY_TX_UUIDS.to_vec(),
            unlock_uuid: LEGACY_UNLOCK_UUID,
            requires_unlock: true,
            supports_pairing: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DecodedPacket {
    pub packet_type: [u8; 2],
    pub eeprom_address: [u8; 2],
    pub data: Vec<u8>,
}

/// Try to reassemble buffered channel data into a packet. Returns `Ok(None)`
/// when more bytes are still expected. Mirrors the inner block of
/// `_callbackForRxChannels` in omblepy.py.
fn try_reassemble(
    buffers: &mut [Option<Vec<u8>>],
    single_channel: bool,
) -> Result<Option<DecodedPacket>> {
    let Some(first) = buffers.first().and_then(|b| b.as_ref()) else {
        return Ok(None);
    };
    if first.is_empty() {
        return Ok(None);
    }
    let packet_size = first[0] as usize;
    let required = if single_channel { 1 } else { (packet_size + 15) / 16 };
    for slot in buffers.iter().take(required) {
        if slot.is_none() {
            return Ok(None);
        }
    }
    let mut combined: Vec<u8> = Vec::with_capacity(required * 16);
    for slot in buffers.iter().take(required) {
        combined.extend_from_slice(slot.as_ref().unwrap());
    }
    combined.truncate(packet_size);
    for slot in buffers.iter_mut() {
        *slot = None;
    }
    let xor: u8 = combined.iter().fold(0u8, |a, &b| a ^ b);
    if xor != 0 {
        bail!(
            "data corruption in rx, xor={xor}, combined={}",
            hex(&combined)
        );
    }
    if combined.len() < 6 {
        bail!("rx packet too short ({} bytes)", combined.len());
    }
    let packet_type = [combined[1], combined[2]];
    let eeprom_address = [combined[3], combined[4]];
    let expected = combined[5] as usize;
    let data = if expected > combined.len().saturating_sub(8) {
        vec![0xff; expected]
    } else if packet_type == [0x8f, 0x00] {
        combined[6..7].to_vec()
    } else {
        combined[6..6 + expected].to_vec()
    };
    Ok(Some(DecodedPacket {
        packet_type,
        eeprom_address,
        data,
    }))
}

/// Tag each channel's notification stream with its index, then merge them
/// into a single stream of `(channel_idx, bytes)` events.
async fn merge_rx_streams(
    rx_chars: &[Characteristic],
) -> Result<SelectAll<BoxStream<'static, (usize, Vec<u8>)>>> {
    let mut streams: Vec<BoxStream<'static, (usize, Vec<u8>)>> = Vec::with_capacity(rx_chars.len());
    for (i, ch) in rx_chars.iter().enumerate() {
        let s = ch
            .notify()
            .await
            .with_context(|| format!("start notify on rx channel {i}"))?;
        streams.push(s.map(move |v| (i, v)).boxed());
    }
    Ok(select_all(streams))
}

fn hex(b: &[u8]) -> String {
    let mut s = String::with_capacity(b.len() * 2);
    for &x in b {
        use std::fmt::Write;
        let _ = write!(s, "{x:02x}");
    }
    s
}

pub struct Protocol {
    pub cfg: ChannelConfig,
    rx_chars: Vec<Characteristic>,
    tx_chars: Vec<Characteristic>,
    unlock_char: Option<Characteristic>,
    rx_stream: Option<SelectAll<BoxStream<'static, (usize, Vec<u8>)>>>,
}

impl Protocol {
    pub async fn new(dev: &Device, cfg: ChannelConfig) -> Result<Self> {
        let services = dev.services().await.context("read gatt services")?;
        let mut parent = None;
        for s in services {
            if s.uuid().await.ok() == Some(cfg.parent_service) {
                parent = Some(s);
                break;
            }
        }
        let parent = parent.ok_or_else(|| {
            anyhow!("parent service {} not found on device", cfg.parent_service)
        })?;
        let chars = parent.characteristics().await?;
        let mut by_uuid = std::collections::HashMap::new();
        for ch in chars {
            let u = ch.uuid().await?;
            by_uuid.insert(u, ch);
        }
        let mut take = |uuid: &Uuid, label: &str| -> Result<Characteristic> {
            by_uuid
                .remove(uuid)
                .ok_or_else(|| anyhow!("characteristic {uuid} ({label}) not found"))
        };
        let mut rx_chars = Vec::with_capacity(cfg.rx_uuids.len());
        for (i, u) in cfg.rx_uuids.iter().enumerate() {
            rx_chars.push(take(u, &format!("rx[{i}]"))?);
        }
        let mut tx_chars = Vec::with_capacity(cfg.tx_uuids.len());
        for (i, u) in cfg.tx_uuids.iter().enumerate() {
            tx_chars.push(take(u, &format!("tx[{i}]"))?);
        }
        let unlock_char = by_uuid.remove(&cfg.unlock_uuid);
        Ok(Self {
            cfg,
            rx_chars,
            tx_chars,
            unlock_char,
            rx_stream: None,
        })
    }

    pub fn unlock_characteristic(&self) -> Option<&Characteristic> {
        self.unlock_char.as_ref()
    }

    async fn enable_rx_notify(&mut self) -> Result<()> {
        if self.rx_stream.is_none() {
            self.rx_stream = Some(merge_rx_streams(&self.rx_chars).await?);
        }
        Ok(())
    }

    async fn disable_rx_notify(&mut self) -> Result<()> {
        // bluer stops the notification when the stream is dropped.
        self.rx_stream = None;
        Ok(())
    }

    async fn send_command(&mut self, command: &[u8]) -> Result<()> {
        let single_tx = self.tx_chars.len() == 1;
        let channel_width = if single_tx {
            std::cmp::max(16, command.len())
        } else {
            16
        };
        let required = (command.len() + channel_width - 1) / channel_width;
        let mut remaining = command;
        for i in 0..required {
            let take = remaining.len().min(channel_width);
            let chunk = &remaining[..take];
            debug!("tx ch{i} > {}", hex(chunk));
            self.tx_chars[i]
                .write(chunk)
                .await
                .with_context(|| format!("write tx ch{i}"))?;
            remaining = &remaining[take..];
        }
        Ok(())
    }

    /// Send the command, accumulate notifications until a packet reassembles,
    /// then return it. Retries up to 5 times on a 1-second silence (matches
    /// the upstream behaviour).
    async fn wait_for_rx_or_retry(&mut self, command: &[u8]) -> Result<DecodedPacket> {
        let single_rx = self.rx_chars.len() == 1;
        for retry in 0..5 {
            self.send_command(command).await?;
            let mut buffers: Vec<Option<Vec<u8>>> = vec![None, None, None, None];
            let stream = self
                .rx_stream
                .as_mut()
                .ok_or_else(|| anyhow!("rx notifications not enabled"))?;
            let collect = async {
                while let Some((idx, bytes)) = stream.next().await {
                    debug!("rx ch{idx} < {}", hex(&bytes));
                    if idx < buffers.len() {
                        buffers[idx] = Some(bytes);
                    }
                    match try_reassemble(&mut buffers, single_rx)? {
                        Some(pkt) => return Ok::<DecodedPacket, anyhow::Error>(pkt),
                        None => continue,
                    }
                }
                bail!("rx stream closed unexpectedly")
            };
            match timeout(Duration::from_secs(1), collect).await {
                Ok(Ok(pkt)) => return Ok(pkt),
                Ok(Err(e)) => return Err(e),
                Err(_) => {
                    warn!("transmission failed, retry {}/5", retry + 1);
                    continue;
                }
            }
        }
        bail!("same transmission failed 5 times, abort")
    }

    pub async fn start_transmission(&mut self) -> Result<()> {
        self.enable_rx_notify().await?;
        let cmd = [0x08, 0x00, 0x00, 0x00, 0x00, 0x10, 0x00, 0x18];
        let pkt = self.wait_for_rx_or_retry(&cmd).await?;
        if pkt.packet_type != [0x80, 0x00] {
            bail!(
                "invalid response to data readout start (type={:02x}{:02x})",
                pkt.packet_type[0], pkt.packet_type[1]
            );
        }
        Ok(())
    }

    pub async fn end_transmission(&mut self) -> Result<()> {
        let cmd = [0x08, 0x0f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x07];
        let pkt = self.wait_for_rx_or_retry(&cmd).await?;
        if pkt.packet_type != [0x8f, 0x00] {
            bail!(
                "invalid response to data readout end (type={:02x}{:02x})",
                pkt.packet_type[0], pkt.packet_type[1]
            );
        }
        if pkt.data.first().copied().unwrap_or(0) != 0 {
            bail!(
                "device reported error status code {} while ending transmission",
                pkt.data[0]
            );
        }
        self.disable_rx_notify().await?;
        Ok(())
    }

    /// Read one block of EEPROM. `blocksize` must fit in a u8.
    pub async fn read_eeprom_block(&mut self, address: u16, blocksize: u8) -> Result<Vec<u8>> {
        let mut cmd: Vec<u8> = vec![0x08, 0x01, 0x00];
        cmd.extend_from_slice(&address.to_be_bytes());
        cmd.push(blocksize);
        let xor = cmd.iter().fold(0u8, |a, b| a ^ b);
        cmd.push(0x00);
        cmd.push(xor);
        let pkt = self.wait_for_rx_or_retry(&cmd).await?;
        let want_addr = address.to_be_bytes();
        if pkt.eeprom_address != want_addr {
            bail!(
                "rx address {:02x?} does not match requested {:02x?}",
                pkt.eeprom_address, want_addr
            );
        }
        if pkt.packet_type != [0x81, 0x00] {
            bail!(
                "invalid packet type {:02x?} in eeprom read",
                pkt.packet_type
            );
        }
        Ok(pkt.data)
    }

    /// Write one block of EEPROM.
    pub async fn write_eeprom_block(&mut self, address: u16, data: &[u8]) -> Result<()> {
        let mut cmd: Vec<u8> = Vec::with_capacity(data.len() + 8);
        cmd.push((data.len() + 8) as u8);
        cmd.extend_from_slice(&[0x01, 0xc0]);
        cmd.extend_from_slice(&address.to_be_bytes());
        cmd.push(data.len() as u8);
        cmd.extend_from_slice(data);
        let xor = cmd.iter().fold(0u8, |a, b| a ^ b);
        cmd.push(0x00);
        cmd.push(xor);
        let pkt = self.wait_for_rx_or_retry(&cmd).await?;
        let want_addr = address.to_be_bytes();
        if pkt.eeprom_address != want_addr {
            bail!(
                "rx address {:02x?} does not match written address {:02x?}",
                pkt.eeprom_address, want_addr
            );
        }
        if pkt.packet_type != [0x81, 0xc0] {
            bail!(
                "invalid packet type {:02x?} in eeprom write",
                pkt.packet_type
            );
        }
        Ok(())
    }

    /// Continuous read across multiple block requests.
    pub async fn read_continuous(
        &mut self,
        mut start: u16,
        mut bytes_to_read: usize,
        block_size: u8,
    ) -> Result<Vec<u8>> {
        let mut out = Vec::with_capacity(bytes_to_read);
        while bytes_to_read != 0 {
            let chunk = std::cmp::min(bytes_to_read, block_size as usize) as u8;
            debug!("read from {start:#x} size {chunk:#x}");
            let block = self.read_eeprom_block(start, chunk).await?;
            out.extend_from_slice(&block);
            start = start.wrapping_add(chunk as u16);
            bytes_to_read -= chunk as usize;
        }
        Ok(out)
    }

    /// Continuous write across multiple block requests.
    pub async fn write_continuous(
        &mut self,
        mut start: u16,
        data: &[u8],
        block_size: u8,
    ) -> Result<()> {
        let mut remaining = data;
        while !remaining.is_empty() {
            let take = remaining.len().min(block_size as usize);
            debug!("write to {start:#x} size {take:#x}");
            self.write_eeprom_block(start, &remaining[..take]).await?;
            start = start.wrapping_add(take as u16);
            remaining = &remaining[take..];
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pad_with_crc(mut bytes: Vec<u8>) -> Vec<u8> {
        let xor = bytes.iter().fold(0u8, |a, b| a ^ b);
        bytes.push(0x00);
        bytes.push(xor);
        bytes
    }

    #[test]
    fn reassemble_single_channel_short_packet() {
        // start-transmission echo: 8 bytes, type 8000.
        let pkt = pad_with_crc(vec![0x08, 0x80, 0x00, 0x00, 0x00, 0x00]);
        let mut buffers: Vec<Option<Vec<u8>>> = vec![Some(pkt), None, None, None];
        let out = try_reassemble(&mut buffers, true).unwrap().unwrap();
        assert_eq!(out.packet_type, [0x80, 0x00]);
        assert_eq!(out.eeprom_address, [0x00, 0x00]);
        assert!(out.data.is_empty());
        assert!(buffers.iter().all(|b| b.is_none()));
    }

    #[test]
    fn reassemble_end_transmission_keeps_status_byte() {
        // type 8f00 special-case: status byte at offset 6 only.
        let pkt = pad_with_crc(vec![0x08, 0x8f, 0x00, 0x00, 0x00, 0x00]);
        let mut buffers: Vec<Option<Vec<u8>>> = vec![Some(pkt), None, None, None];
        let out = try_reassemble(&mut buffers, true).unwrap().unwrap();
        assert_eq!(out.packet_type, [0x8f, 0x00]);
        assert_eq!(out.data, vec![0x00]);
    }

    #[test]
    fn reassemble_multi_channel_waits_until_all_chunks_arrive() {
        // 32-byte packet, type 8100, 16 bytes of data, spans 2 channels.
        let mut data = vec![0x20, 0x81, 0x00, 0x12, 0x34, 0x10];
        for i in 0..16u8 {
            data.push(i);
        }
        let pkt = pad_with_crc(data);
        let first = pkt[..16].to_vec();
        let second = pkt[16..].to_vec();

        let mut buffers: Vec<Option<Vec<u8>>> = vec![Some(first), None, None, None];
        assert!(try_reassemble(&mut buffers, false).unwrap().is_none());
        buffers[1] = Some(second);
        let out = try_reassemble(&mut buffers, false).unwrap().unwrap();
        assert_eq!(out.packet_type, [0x81, 0x00]);
        assert_eq!(out.eeprom_address, [0x12, 0x34]);
        assert_eq!(out.data.len(), 16);
        assert_eq!(out.data, (0..16u8).collect::<Vec<_>>());
    }

    #[test]
    fn reassemble_rejects_bad_crc() {
        let mut pkt = pad_with_crc(vec![0x08, 0x80, 0x00, 0x00, 0x00, 0x00]);
        *pkt.last_mut().unwrap() ^= 0xff;
        let mut buffers: Vec<Option<Vec<u8>>> = vec![Some(pkt), None, None, None];
        let err = try_reassemble(&mut buffers, true).unwrap_err();
        assert!(format!("{err}").contains("data corruption"));
    }
}
