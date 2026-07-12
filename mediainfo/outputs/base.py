"""Base class for output plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Optional, Tuple

from mediainfo.app_services import AppServices
from mediainfo.cache import ImageCache
from mediainfo.models import Artwork, NowPlaying


class Output(ABC):
    """Something that displays the current "now playing" artwork."""

    # Registry key this output is known by (e.g. "pixoo") - None (the
    # default) means "not self-declared", i.e. look it up via
    # registries.output_name_for_class() as today.
    name: Optional[str] = None

    # Optional: the config dataclass (from mediainfo.config) that
    # configures this output, for a plugin that wants to declare the
    # pairing itself rather than relying on registries.py's OUTPUT_CLASSES
    # and mediainfo.config's OUTPUT_CONFIG_TYPES staying in sync by
    # registry key alone. None (the default) means "not declared".
    config_class: Optional[type] = None

    # Optional free-form feature flags - not consumed anywhere yet; a hook
    # for future capability queries without another base-class change.
    capabilities: frozenset = frozenset()

    # Set to False on text-only outputs (e.g. Ulanzi) so that idle wallpaper
    # images are not routed to them.
    handles_images: bool = True

    # Set to True (e.g. on PixooOutput) to skip artist-photo images
    # (Artwork.is_artist_photo) while showing music, so this output only
    # ever shows actual album/cover art - never an unrelated artist bio
    # photo from the rotation pool. No effect outside music, since
    # artist photos only ever get added for media_type == "music".
    music_album_art_only: bool = False

    # Set to True (e.g. on WebOutput) to include lyrics word-cloud images
    # (Artwork.is_wordcloud) in this output's rotation - False (the
    # default) skips them everywhere else, since a dense text overlay
    # doesn't read well on a small LED matrix or photo frame.
    show_wordclouds: bool = False

    # List of Transform objects applied to every image before update() is
    # called.  Populated from the output's config `transforms:` key.
    transform_pipeline: List = []

    @abstractmethod
    def update(
        self, now_playing: NowPlaying, artwork: Artwork, image_path: Path
    ) -> None:
        """Show new artwork."""

    def on_idle(self) -> None:
        """Called once when nothing is playing. Default: do nothing."""

    def on_new_item(self, now_playing: NowPlaying, cache: ImageCache) -> None:
        """Called once when the playing item changes, with access to all of
        its available images (not just the one currently shown/rotated).
        Default: do nothing.
        """

    def on_schedule_tick(self) -> None:
        """Called every orchestrator poll tick, regardless of what's
        playing or whether this output is filtered - the hook for
        time-based device housekeeping like power/brightness scheduling
        (see display_schedule.py). Implementations must be cheap when
        nothing needs doing and must not raise. Default: do nothing.
        """

    # -- lifecycle ----------------------------------------------------
    #
    # Groundwork toward hot-reloading outputs (see wiring.instantiate_outputs()
    # and __main__._warn_output_changes()) - outputs today do all their
    # setup in __init__ and are built once for the life of the process;
    # a config change to `outputs:` still needs a full restart. These
    # three are called (start()/stop() only, for now - see below) but
    # default to no-ops, so existing outputs that do everything in
    # __init__ are unaffected.

    def start(self) -> None:
        """Called once, right after construction (see
        wiring.instantiate_outputs()). Default: do nothing - existing
        outputs that start background threads/servers in __init__ don't
        need to change; new outputs can do that work here instead, as a
        step toward eventually supporting stop()+start() instead of a
        full process restart.
        """

    def stop(self) -> None:
        """Called once during graceful shutdown, before on_idle() (see
        __main__._shutdown_outputs()). Default: do nothing.
        """

    def attach(self, services: AppServices) -> None:
        """Called once, after the orchestrator (and therefore every
        AppServices field) exists - see wiring.attach_services(). Pull
        whatever fields this output cares about (health_provider, history,
        mediadata_store, overrides, get_hitster_safe/set_hitster_safe,
        request_artwork_refresh/request_rotation_now) and ignore the rest.
        Called again, with a fresh AppServices, on every config hot-reload -
        implementations should simply overwrite their own state each time,
        the same as a plain setter would. Default: do nothing, for outputs
        that need none of this.
        """

    def reload(self, config: Any) -> None:
        """Not yet called anywhere - declared now so a plugin can opt in
        early. The intent is for a future config-file hot-reload to call
        this with the plugin's new config instead of requiring a full
        process restart for `outputs:` changes (see
        __main__._warn_output_changes()); matching reloaded config
        entries back to existing (possibly multi-instance) output objects
        isn't solved yet. Default: do nothing.
        """

    def health_check(self) -> Optional[dict]:
        """Optional self-reported health detail beyond what the
        orchestrator already tracks generically (call success/error -
        see orchestrator_health.py). None (the default) means nothing
        extra to report.
        """
        return None

    def test_connection(self) -> Tuple[bool, str]:
        """Optional connectivity check for the config UI's "test
        connection" button. Default: not implemented here - today this is
        instead dispatched by type name in
        mediainfo/outputs/config_dashboard.py (test_output()); migrating
        an individual plugin's test logic to this method is a reasonable
        future increment, one plugin at a time, rather than all at once.
        """
        return False, "No connection test available for this plugin"
