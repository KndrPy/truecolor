"""Immutable prior-art artifact intake.

Concrete intake functions intentionally remain in
``analysis.prior_art.ingestion.artifact_intake``.

The package initializer does not import executable submodules eagerly.
This preserves predictable ``python -m`` execution and prevents the
target module from being loaded before runpy executes it.
"""

__all__: list[str] = []
