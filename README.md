# Cinematic camera moves

Arc, dolly, truck, pedestal, tracking, pass-through, helix, whip pan, handheld and a dolly zoom that holds its subject's screen size exactly. Pure Python emitting keyframes -- no DCC imports, so it drives Max, Maya, Blender or anything else.

Part of Atlas. Extracted as a standalone tool; nothing here imports anything
outside this folder.

## Layout

```
server/cinecam.py       the moves. No host import, ever.
server/movespec.py      which spinner is which argument, as data
server/maxui.py         that table, rendered as a MAXScript rollout
server/cinecam_max.py   the only file that imports 3ds Max
install_cinecam.ms      run this once
tests/                  run these first
```

## The 3ds Max rollout

Run `install_cinecam.ms` once — Scripting > Run Script, or drag it into a
viewport. Every camera in the scene grows a **Cinematic move** rollout at the
end of its Modify panel; cameras made afterwards get one as they are created,
and scenes opened afterwards get one on open. The installer offers to write a
startup script so this survives a restart; say no and it is a per-session thing.

Three rollouts, all of it adjustable in place:

- **Cinematic move** — pick the technique, the frame range, and the subject
  (a scene node sampled per frame, or a fixed point). The spinners for the
  eight other techniques stay visible but greyed, so what a move does and does
  not use is legible rather than hidden.
- **Texture and guards** — handheld, ground clearance, and the refusal limits.
- **Apply** — *Build the move* runs the guards and then keys the camera.
  *Check without keying* runs the same guards and reports, touching nothing.
  *Read placement from viewport* fills the bearing, standoff and height in from
  wherever you just dragged the camera, which is faster than typing them.

A refused move changes nothing and says what is wrong with the shot. The
one-line result stays in the status box after the dialog is dismissed.

The rollout is stored in the .max file, so a camera keeps it on a machine where
the installer never ran. Its buttons need the Python side; without it they say
so and name the script to run.

## Run the tests

```
python -m pytest tests -q
```

3 test files ship with this product. They cover the moves, the parameter table,
and the generated MAXScript — the table is checked against `cinecam`'s real
signatures by introspection, so a spinner cannot quietly stop being wired to
anything.

Nothing in the tests imports a host, which is also their limit: they prove the
generated MAXScript is well-formed and complete, not that 3ds Max likes it. See
*Compatibility*.

## Requirements

Python 3.11+. The tests are offline and need no 3ds Max, no Houdini and no
network.

The rollout additionally needs a 3ds Max with `pymxs` and the MAXScript
`python` interface — 2021 or later. `cinecam.py` itself needs neither and never
will.

## Data licensing

This is source code, licensed however you choose. The *data* it fetches is
not:

- OpenStreetMap is ODbL 1.0 -- attribution, and share-alike on derived
  databases.
- Copernicus GLO-30 requires attribution.
- Poly Haven textures are CC0.

`attribution.py`, where included, generates the manifest for you.

## Compatibility

Every 3ds Max and V-Ray parameter name in `cinecam.py`'s original callers was
read off a live 3ds Max 2027 with V-Ray 7 update 3. Names are discovered from
the host rather than recalled, but they were discovered on *that* host. Treat
other versions as unverified until checked.

**The rollout is not in that category and should not be treated as if it were.**
`maxui.py` and `cinecam_max.py` were written without a live host: the MAXScript
they emit is checked for structure and completeness by `test_maxui.py`, and the
parameter table is checked against real function signatures, but no test in this
repo has ever asked 3ds Max whether it accepts the result. The first run is the
verification. The things to watch on it, in the order they would bite:

- whether `custAttributes.add` on a camera's base object puts the rollout where
  this claims it does;
- whether `custAttributes.getOwner this` resolves inside a rollout handler, and
  whether the selection fallback covers it when it does not;
- `edittext ... readOnly:true`, `pickbutton ... autoDisplay:true`, and the
  `#worldUnits` parameter type;
- whether `node.fov` is the horizontal FOV on the camera you are using. The
  moves emit a generic angular field of view and this writes it straight to
  `.fov`; on a V-Ray physical camera that is not the same quantity.
