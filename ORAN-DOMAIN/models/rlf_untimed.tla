------------------------------- MODULE rlf_untimed -------------------------------
(* TS 38.331 5.3.10.1 - 5.3.10.3 (radio link failure detection), with time
   abstracted away: T310 expiry is an ordinary action that the environment may
   interleave anywhere between L1 indications. This is the untimed companion
   to the UPPAAL model rrc_rlf.xml, which keeps dense time. Constants match
   the UPPAAL model: N310=2, N311=2, OOS budget 6, IS budget 4, T310=4.      *)
EXTENDS Integers

CONSTANTS N310, N311, OOS_BUDGET, IS_BUDGET, T310_TICKS

VARIABLES phase,   \* "C" connected, T310 not running | "P" T310 running | "RLF"
          nOOS,    \* consecutive out-of-sync streak accumulated while in C
          nIS,     \* consecutive in-sync streak accumulated while in P
          oosLeft, \* adversarial L1 budget of out-of-sync indications
          isLeft,  \* adversarial L1 budget of in-sync indications
          t310,    \* -1 not running, else abstract ticks elapsed since start
          started  \* TRUE once T310 has been started at least once

vars == <<phase, nOOS, nIS, oosLeft, isLeft, t310, started>>

Init == /\ phase = "C"
        /\ nOOS = 0 /\ nIS = 0
        /\ oosLeft = OOS_BUDGET /\ isLeft = IS_BUDGET
        /\ t310 = -1
        /\ started = FALSE

(* 5.3.10.1: N310 consecutive out-of-sync while T310 is not running starts T310 *)
OOS == /\ phase = "C"
       /\ oosLeft > 0
       /\ oosLeft' = oosLeft - 1
       /\ isLeft' = isLeft
       /\ nIS' = 0
       /\ nOOS' = nOOS + 1
       /\ IF nOOS' >= N310
            THEN /\ phase' = "P"
                 /\ t310' = 0
                 /\ started' = TRUE
            ELSE /\ phase' = "C"
                 /\ t310' = t310
                 /\ started' = started

(* an out-of-sync arriving while T310 runs changes nothing (clause only starts *)
OOS_in_P == /\ phase = "P"
            /\ oosLeft > 0
            /\ oosLeft' = oosLeft - 1
            /\ isLeft' = isLeft
            /\ nOOS' = nOOS /\ nIS' = nIS
            /\ t310' = t310 /\ started' = started
            /\ phase' = "P"

(* in-sync while connected breaks the out-of-sync streak (consecutiveness)   *)
IS_in_C == /\ phase = "C"
           /\ isLeft > 0
           /\ isLeft' = isLeft - 1
           /\ oosLeft' = oosLeft
           /\ nOOS' = 0 /\ nIS' = 0
           /\ t310' = t310 /\ started' = started
           /\ phase' = "C"

(* 5.3.10.2: N311 consecutive in-sync while T310 is running stops T310        *)
IS_stop == /\ phase = "P"
           /\ isLeft > 0
           /\ nIS + 1 >= N311
           /\ isLeft' = isLeft - 1
           /\ oosLeft' = oosLeft
           /\ phase' = "C"
           /\ t310' = -1
           /\ nIS' = 0
           /\ nOOS' = 0
           /\ started' = started

IS_wait == /\ phase = "P"
           /\ isLeft > 0
           /\ nIS + 1 < N311
           /\ isLeft' = isLeft - 1
           /\ oosLeft' = oosLeft
           /\ nOOS' = nOOS
           /\ phase' = "P"
           /\ t310' = t310
           /\ nIS' = nIS + 1
           /\ started' = started

IS == IS_stop \/ IS_wait

(* 5.3.10.3: T310 expiry declares radio link failure; terminal               *)
Tick == /\ phase = "P"
        /\ t310' = t310 + 1
        /\ IF t310' >= T310_TICKS
             THEN phase' = "RLF"
             ELSE phase' = "P"
        /\ nOOS' = nOOS /\ nIS' = nIS
        /\ oosLeft' = oosLeft /\ isLeft' = isLeft
        /\ started' = started

(* idle: C has no invariant in the UPPAAL model - it may wait forever *)
Stay == phase = "C" /\ UNCHANGED vars

Done == phase = "RLF" /\ UNCHANGED vars

Next == OOS \/ OOS_in_P \/ IS_in_C \/ IS \/ Tick \/ Stay \/ Done
Spec == Init /\ [][Next]_vars

(* -------------------------------------------------------------------------- *)
TypeOK == /\ phase \in {"C","P","RLF"}
          /\ nOOS \in 0..N310
          /\ nIS \in 0..N311
          /\ oosLeft \in 0..OOS_BUDGET
          /\ isLeft \in 0..IS_BUDGET
          /\ t310 \in (-1)..T310_TICKS
          /\ started \in {TRUE, FALSE}

(* pigeonhole: with OOS_BUDGET > (IS_BUDGET+1)*(N310-1), exhausting both
   budgets without ever starting T310 is impossible - 6 out-of-syncs split
   by at most 4 in-syncs must leave a streak of 2 (N310)                  *)
StartedWhenExhausted == (oosLeft + isLeft) > 0 \/ started

(* RLF is declared only by T310 expiry (5.3.10.3), never out of the blue    *)
RLFOnlyAfterStart == phase # "RLF" \/ started

(* probes - each is EXPECTED to be violated; TLC's counterexample trace is
   the witness trace. Together they show the untimed model admits BOTH
   outcomes of the T310 race, i.e. cannot decide the race.               *)
NoRLF == phase # "RLF"
NoRecovery == ~(phase = "C" /\ t310 = -1 /\ started)
================================================================================