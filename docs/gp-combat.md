# P4: the player's combat

**Status: DESIGN for M7 phase P4** (`docs/handoff-gameplay.md` section 10, P4). It was written on
2026-10-04, after phase 3 merged (#116). The owner's direction that day: "continue to the next
phases, dont stop until 5 is merged". Kill criteria and budgets are declared per rung in
`docs/gp-ledger.md` before each build.

---

## 0. The decisions taken (coordinator, under the owner's 2026-09-30 "be autonomous" rule)

| id | decision | why |
|---|---|---|
| C1 | P4 ships in THREE rungs. **P4.0** is the screen: the 160x84 view, the status bar, and the ready weapon drawn. **P4.1** is the trigger (the aim window moved to P4.2: "fire" never reads a shot's outcome, so its rolls need no target): the key map, strafe, the weapon state machine, ammo, and shots resolved and rolled but applying nothing (`player="fire"`). **P4.2** is the hit: damage, pain, death, corpses, drops and the noise alert (`player="hit"`). | A build is ~2.5 h plus ~1.5 h of evidence, so fewer rungs. Each rung has one model mode it is exact against, as P3's did. |
| C2 | **The size target rises to 40% of 2^27.** P4 is estimated to land at 35.2-36.7%, and P5 adds the fight sprites. | The owner's 2026-09-25 note: "35% conflicts with even 2 levels -- raise it". On 2026-10-03 the owner was asked "raise the target, or buy space back?" and answered "continue". The 22M ops cap is unchanged and still binding. |
| C3 | **The status bar is option C** (section 2): a flat dark bar in the MENU's fonts. Numbers are red in the 5x7 font, labels gray in the 3x5 font, owned weapons yellow, and the blue key a card. It is not DOOM's STBAR downscaled. | The prototypes were rendered: `scratchpad/plan/p4/hud` in the session, copied to `docs/gp-combat/`. STBAR at half resolution makes its labels illegible ("AMMO" and "HEALTH" are mush). Option C reads cleanly and matches the menu the owner chose. |
| C4 | **The weapon is a KEEP overlay** (`docs/gp-partial-ditto.md` 5(b)): records after the view, `[x][0xFC][wtop][pairs/keeps][0xFF]`. The view's dittos become partial dittos, `[x][0xFD][84][0xFF]`. | The world emitter is unchanged and every ditto survives. |
| C5 | **No v6** unless the 84-row view changes which monsters the renderer marks seen on v5. That is checked host-side before the first build. | v5 is frozen by the owner. A change in seen moves the AI and so the trajectory. |
| C6 | **Player blocking by solid things moves to P6**, with the pickup touch loop that DOOM runs in the same P_CheckPosition. | No phase owned it. P6 already walks the specials at every tried position. |
| C7 | The flipjump device change is a D9 PR into `1.5.1` (branch `screen-partial-ditto`). The build refuses to emit the tokens against a device that lacks them. | D9. The failure must be loud and early. |

## 1. The model modes

`World(player=...)`: `PLAYER_MODES = ("walk", "fire", "hit", "full")`, alongside `MONSTER_MODES`.
`wall_renderer.PLAYER_MODE` sits next to `MONSTER_MODE`. Each mode draws every random number the
full model draws, so the next rung adds effects without moving a roll (the P3.2c rule).
- **walk**: today. No weapon.
- **fire** (P4.1): the weapon keys, the psprite state machine, ammo, refire, the `rng_player`
  rolls, and the target resolved through the aim window. Nothing is applied.
- **hit** (P4.2): `damage_monster` / `_kill_monster` and the noise alert. Still no effects (P5),
  barrels and pickups (P6), or damage to the player (P5).

The gate oracles keep ONE layer, `monsters.MonsterPhase`, which grows a weapon half: damage must
land on the same monster cells the gates already step.

## 2. The screen (P4.0)

- **View**: game tier only. `VIEW_H = 84`, `CENTERY = 42`. `CENTERX` and `PROJECTION` are
  unchanged, so wall and sprite scales and every column are unchanged; only the rows clip. The
  hosted tiers and deg_gate's visual tier stay at 100.
- **Bar**: rows 84..99, drawn from cells, as records after the view: `[x][0xFC][84][pairs][0xFF]`
  for the columns whose content changed. The whole bar is redrawn after any menu frame and at
  level start. Panels: AMMO, HEALTH, ARMS (2 3 4), ARMOR, KEYS.
- **Weapon**: the ready pistol `PISGA0` at WEAPONTOP (no bob, D5), lit by the player's sector
  light. The overlay records come after the view and before the bar.
- **Aim window**: moved to P4.1, where the trigger first reads it (`docs/gp-aim-window.md`). `aim_sid[17]` is
  recorded at column-open time and persisted; `aim_tz` is reset each frame.

## 3. Verification (every rung)

The gates must be byte- and state-exact against the oracle: m2_std_gate, m3_gate, p2a_gate and
B0 v5. Their selftests must be rejected where they should be. deg_gate must be unchanged (it uses
the visual tier). The restore sets are re-keyed. Every new fj leaf gets a tests/fj harness with
strict mutant controls (R9), and the device tokens get flipjump unit tests plus a cross-decoder
fuzz in doom.

## 4. P4.1, the trigger (as designed; the ledger declares it)

- **Keys**: the owner's map. A / D and ',' / '.' strafe, only the arrows turn, ctrl fires, and 1..4 are held flags.
  `input.fj` binds them; `menu.HELP_ROWS` lists them and nothing else (`test_keyboard_input` runs the poll on every
  key the screen names).
- **Strafe**: `step_sim(strafe=True)` is the model's side step, and so is the game tier's `_player_sim_lines`.
- **The weapon** (`doomfj.weaponcode`):
  - one baked block per psprite state, with a nested P_SetPsprite as a tail jump;
  - targets that depend on the ready weapon dispatch on `wp_rdy`;
  - the flash is an fcall'd chain;
  - each shot advances the player's stream by its draws.
- **The overlay**: the weapon frame `wp_frm`, then the flash frame `fl_frm` over it. The bar's ammo comes from
  `ammobcd` and its arms from `wp_own`, both written each tic.
- **The gates**: `MonsterPhase` grows a weapon half (`weapon`, `weapon_state`, `screen_kw`) in the world's player
  mode.
  - m2_std_gate's first walk holds and taps fire and switches to the fist and back.
  - B0 delivers only its five keys, as before. The model's strafe reaches the binary through the injected pose, and
    the binary's weapon only rises and idles there.
