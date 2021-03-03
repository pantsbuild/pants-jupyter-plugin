import subprocess
from textwrap import dedent


def test_pex_load(tmpdir) -> None:
    pex_file = tmpdir / "colors.pex"
    subprocess.run(["pex", "ansicolors==1.1.8", "-o", pex_file], check=True)
    subprocess.run(
        [
            "ipython",
            "-c",
            dedent(
                f"""\
                try:
                    import colors
                    raise AssertionError(
                        "Should not have been able to import colors before loading {pex_file}."
                    )
                except ImportError:
                    # Expected.
                    pass

                %load_ext pants_jupyter_plugin
                %pex_load {pex_file}
                import colors
                """
            ),
        ],
        check=True,
    )
