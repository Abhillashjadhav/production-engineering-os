# PR227 source-admission scope

This patch keeps the approved source-only startup requirement and narrows one unsafe
inference. A gated process refuses when the Linux kernel startup records needed for
its bytecode-prefix check are unavailable. The named engine root must resolve to a
regular `.py` source file; a ZIP or sourceless origin at that root is refused.
The existing implementation-class check still requires inspectable source and
matching compiled methods.

The guard observes that bytecode writes are disabled and that the recorded prefix
matches an empty directory **when checked**. It does not prove the directory was
empty throughout startup or that no other process changed it. The named source
manifest binds listed file bytes; it does not inventory every loaded helper,
prevent future ZIP/sourceless imports, or authenticate mutable referenced globals
against code already running in this interpreter.

`validate_process_inputs` uses this inventory for bound digest gates before
workspace creation. A digest-boundary `PASS` means the named files and recorded
boundary observations matched. It is not a certificate of complete Python import
history or hostile same-process authenticity. The earlier W2 owner decision to
require source-only startup remains; this document corrects the broader inference
in its historical record without rewriting that decision.

Independent candidate-response verification belongs to the separate trusted
outside-process verifier work. This PR does not provide that boundary, change host
security, authenticate an unrestricted outer provider, or claim general provenance.
