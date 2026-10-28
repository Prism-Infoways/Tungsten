"""Move a Laravel Filament admin to Tungsten.

    tungsten-filament scan ../my-laravel-app          # what can be converted, what needs a human
    tungsten-filament convert ../my-laravel-app       # write tungsten_admin/ next to you

The converted admin uses the same database as the Laravel app (no data copy) and
the same logins (Laravel's bcrypt passwords work as they are).
"""

from .generate import build, write
from .runtime import LaravelHasher, laravel_database_url, laravel_secret_key, slug

__version__ = "0.1.1"

__all__ = ["LaravelHasher", "__version__", "build", "laravel_database_url", "laravel_secret_key", "slug", "write"]
