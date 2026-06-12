"""The dos action, auto-discovered by the rails config loader (issue #51).

The factory is called ONCE, when the rails app loads this module — so the
`CommitClaim()` baseline pins to HEAD at app start, and anything an agent
lands after that is visible to the read-back.
"""

from dos.drivers._effect_gate import CommitClaim
from dos.drivers.nemo_action import make_dos_effect_check

dos_effect_check = make_dos_effect_check(".", expect=[CommitClaim()])
