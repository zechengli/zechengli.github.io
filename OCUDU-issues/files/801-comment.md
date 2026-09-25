Comment for https://gitlab.com/ocudu/ocudu/-/work_items/801 (closed)

---

Thanks for the quick fix in !1536. Two small follow-ups:

**1. The path was reachable before 2b9caf2bcb.** The commit message says it "was already prevented by valid_nack", but on clean 9c99f406 a fresh bearer receiving STATUS `ACK_SN=1, NACK_SN=0` (i.e. `ACK_SN = TX_Next + 1`, `NACK_SN = TX_Next`) through `on_status_pdu()` aborts with `segmented_circular_map.h:536: Assertion 'contains(key)' failed - Accessing non-existent ID=0` (Debug build; 4/4 runs: 12- and 18-bit, fresh bearer and after one SDU with `ACK_SN=2, NACK_SN=1`). `valid_nack()` does not stop it: it only rejects `NACK_SN > TX_Next` (strict), and `NACK_SN < ACK_SN` holds because `handle_status_pdu()` allows `ACK_SN = TX_Next + 1`.

**2. The new regression test also passes on the unfixed code.** `invalid_nack_nack_sn_not_yet_added_to_tx_window` uses `ack_sn = nack_sn = 12`, which `valid_nack()` rejects ("nack_sn=12 >= ack_sn=12") before `handle_nack()` is reached. The test below goes through `handle_nack()`: it passes on HEAD 8fe05a213f ("Invalid nack_sn=0. tx_next_ack=0 tx_next=0") and aborts on 9c99f406 with the assert above. Feel free to use it.

<details><summary>Test (applies to 8fe05a213f)</summary>

```diff
diff --git a/tests/unittests/rlc/rlc_tx_am_test.cpp b/tests/unittests/rlc/rlc_tx_am_test.cpp
index 032c635f41..676813f4e3 100644
--- a/tests/unittests/rlc/rlc_tx_am_test.cpp
+++ b/tests/unittests/rlc/rlc_tx_am_test.cpp
@@ -1568,6 +1568,25 @@ TEST_P(rlc_tx_am_test, invalid_nack_nack_sn_not_yet_added_to_tx_window)
   ASSERT_EQ(st1.tx_next_ack, 5); // TX_NEXT_ACK should have not changed.
 }
 
+TEST_P(rlc_tx_am_test, invalid_nack_nack_sn_equal_to_tx_next_on_fresh_bearer)
+{
+  // Nothing has been sent yet: TX_Next_Ack = TX_Next = 0 and the TX window is empty.
+  // ACK_SN = TX_Next + 1 and NACK_SN = TX_Next pass valid_nack() and reach handle_nack().
+  rlc_am_status_pdu status_pdu(sn_size);
+  status_pdu.ack_sn = 1;
+  {
+    rlc_am_status_nack nack = {};
+    nack.nack_sn            = 0; // NACK an SN that was never transmitted and is not in the tx window.
+    status_pdu.push_nack(nack);
+  }
+
+  rlc->on_status_pdu(std::move(status_pdu));           // NACK should be rejected.
+  ASSERT_EQ(rlc->get_buffer_state().pending_bytes, 0); // No RETX scheduled.
+  rlc_tx_am_state st = rlc->get_state();
+  ASSERT_EQ(st.tx_next_ack, 0);
+  ASSERT_EQ(st.tx_next, 0);
+}
+
 TEST_P(rlc_tx_am_test, invalid_nack_sn_larger_than_ack_sn)
 {
   const uint32_t sdu_size = 4;
```

</details>
