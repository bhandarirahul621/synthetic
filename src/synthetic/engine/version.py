"""Engine version.

FR10 promises that *schema + seed + engine version* always gives byte-identical
output. Bump this constant whenever a change could alter generated values for
an existing schema and seed (a new generator, a different sampling order, a new
dependency version that changes Faker output, and so on).

Format: ``YEAR.MONTH.PATCH`` (matches the PRD §9.1.4 example).
"""

ENGINE_VERSION = "2026.11.0"
