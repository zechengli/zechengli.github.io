# OCUDU issue drafts — index

Each NN.md: line 1 = Title, line 2 = suggested labels; paste everything after the '---' line as the issue body. NN-repro.patch = same regression test as in the <details> block (applies to dev 8fe05a213f).

| No. | Title | Internal ID |
|---|---|---|
| 01 | CU-CP: RRC reestablishment during a pending PDU session setup/modify releases the reestablished UE | CR-8 |
| 02 | CU-CP: failed source UE Context Modification in handover leaves the source UE unreleased (UE stuck) | MC-9 |
| 03 | PDCP TX: full UE DL queue returns last crypto token on crypto thread (data race, off-strand resume) | CR-3 |
| 04 | RRC: reestablishment timeout after context transfer never releases the new UE (NGAP/E1/F1 kept) | MC-8 |
| 05 | F1-U CU-UP: 256 contiguous SDU discards wrap block_size to 0 (discarded SDUs still sent by RLC) | MC-3 |
| 06 | PDCP TX: discard timer restarted with 0 ms after expiry (next SDUs discarded before their deadline) | CR-4a |
| 07 | PDCP TX: reset() leaves the discard timer running on UM re-establishment (new SDU discarded early) | CR-6 |
| 08 | PDCP TX: stale crypto reordering timer drops retransmissions after AM re-establishment (DL loss) | MC-6 |
| 09 | PDCP RX: PDU received before t-Reordering expiry is dropped while its crypto is running (UL SDU loss) | CR-5 |
| 10 | PDCP TX: TX_NEXT_ACK parked on a COUNT removed by a status report (DL stall in Release, assert abort) | CR-4b |
| 11 | PDCP RX: RCVD_HFN underflows in the first hyperframe (one PDU triggers max COUNT and bearer release) | MC-4 |
| 12 | PDCP RX: PDUs buffered during a CU-UP key change are processed with the new keys, is this intended? | MC-5 |
| 13 | RLC RX: t-Reassembly=ms0 is accepted but aborts the DU on the first gap (never expires in Release) | CR-7a |
| 14 | RLC AM TX: t-PollRetransmit expiry re-queues an SN whose RETX is still pending (early max-retx) | CR-2 |
| 15 | RLC AM RX: one failed defer in get_status_pdu() blocks STATUS reports on the bearer for good | CR-1 |
| 16 | RLC UM RX: t-Reassembly checks the gap of RX_Next_Highest instead of RX_Next_Reassembly (SDU lost) | MC-7 |
| 17 | RLC TX: buffer state updates stop after the cell strand discards one queued update task (DL stall) | MC-1 |
| 18 | RLC UM RX: t-Reassembly stop check ignores SN wrap-around (timer keeps running after gap is filled) | CR-7b |
| 19 | RLC AM TX: t-PollRetransmit does not trigger a RETX when the shared TX window pool is exhausted | MC-2 |
