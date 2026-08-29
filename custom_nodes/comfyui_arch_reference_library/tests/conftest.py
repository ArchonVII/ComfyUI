import warnings


# The machine's optional NVML compatibility package emits this while Torch is
# imported during test collection. It is unrelated to the custom node and has
# no actionable call site inside this package.
warnings.filterwarnings(
    "ignore",
    message="The pynvml package is deprecated.*",
    category=FutureWarning,
)


def pytest_configure(config):
    config.addinivalue_line(
        "filterwarnings",
        "ignore:The pynvml package is deprecated.*:FutureWarning",
    )
