"""Native layer sensitivity changes declared workflow selection while preserving raw metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.native_layer_records import NativeLayerVariant
from crosstalk.native_layers.cohort import summarize_layers
from crosstalk.native_layers.cohort_records import CohortSettings
from crosstalk.native_layers.records import LayerSettings

if TYPE_CHECKING:
    from crosstalk.native_layer_records import NativeRunSettings
    from crosstalk.native_layers.cohort_records import ViewName
    from crosstalk.native_layers.records import IssueLayers, LayerView


def _restricted(view: LayerView, threshold: float) -> LayerView:
    """Only the declared workflow flag changes; selections and all measured values stay intact."""
    return view.model_copy(
        update={
            "exploratory_native_rich": view.text.tokens > 0
            and view.low_text_fraction is not None
            and view.low_text_fraction <= threshold
        }
    )


def variants(
    issues: tuple[IssueLayers, ...], settings: NativeRunSettings
) -> tuple[NativeLayerVariant, ...]:
    """Raw, wrapper-minus and threshold views each expose their own source-issue denominator."""
    views: tuple[ViewName, ...] = ("raw-native", "native-minus-matched-repository-wrapper")
    baseline = tuple(
        NativeLayerVariant(
            label=view,
            maximum_low_text_fraction=None,
            cohort=summarize_layers(
                issues, CohortSettings(view=view, bootstrap=settings.bootstrap)
            ),
        )
        for view in views
    )
    restricted: list[NativeLayerVariant] = []
    for threshold in settings.thresholds:
        selected = tuple(
            issue.model_copy(
                update={
                    "settings": LayerSettings(maximum_low_text_fraction=threshold),
                    "raw": _restricted(issue.raw, threshold),
                    "wrapper_excluded": _restricted(issue.wrapper_excluded, threshold),
                }
            )
            for issue in issues
        )
        restricted.append(
            NativeLayerVariant(
                label=f"wrapper-minus/native-rich:maximum-low-text-fraction={threshold:g}",
                maximum_low_text_fraction=threshold,
                cohort=summarize_layers(
                    selected,
                    CohortSettings(
                        view="native-minus-matched-repository-wrapper",
                        bootstrap=settings.bootstrap,
                        native_rich=True,
                    ),
                ),
            )
        )
    return (*baseline, *restricted)
