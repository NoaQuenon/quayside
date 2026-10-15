import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from typer import Argument, Exit, Option, Typer

from quayside.render import build_plan
from quayside.runtime import Testbed
from quayside.runtime.testbed import DEFAULT_WORKDIR
from quayside.spec import Scenario, load_scenario

app = Typer(no_args_is_help=True, help=__doc__)

ScenarioArg = Annotated[Path, Argument(exists=True, dir_okay=False, help="Scenario YAML file")]
WorkdirOpt = Annotated[Path, Option(help="Where rendered projects are kept")]
SetOpt = Annotated[
    list[str] | None, Option("--set", "-s", help="Override a value (e.g., links.factory-edge.latency=20ms)")
]


def _load(path: Path, overrides: list[str] | None) -> Scenario:
    try:
        return load_scenario(path, overrides or [])

    except (ValidationError, ValueError) as e:
        typer.secho(f"invalid scenario {path}:\n{e}", fg="red", err=True)
        raise Exit(1) from None


@app.command()
def validate(scenario: ScenarioArg, set_: SetOpt = None) -> None:
    """Checks a scenario and prints its resolved addressing and routes"""

    scn = _load(scenario, set_)

    try:
        plan = build_plan(scn)

    except ValueError as e:
        typer.secho(str(e), fg="red", err=True)
        raise Exit(1) from None

    typer.echo(json.dumps(plan.to_dict() | {"scenario": "<omitted>"}, indent=2))


@app.command()
def render(scenario: ScenarioArg, set_: SetOpt = None, workdir: WorkdirOpt = DEFAULT_WORKDIR) -> None:
    """Writes the Docker Compose project and plan without starting anything"""

    scn = _load(scenario, set_)
    testbed = Testbed(scn, workdir)
    path = testbed.render()

    typer.echo(path)


@app.command()
def up(
    scenario: ScenarioArg,
    set_: SetOpt = None,
    workdir: WorkdirOpt = DEFAULT_WORKDIR,
    build: Annotated[bool, Option(help="Rebuild local images")] = True,
) -> None:
    """Starts the testbed"""

    scn = _load(scenario, set_)
    testbed = Testbed(scn, workdir)
    testbed.up(build=build)

    typer.secho("testbed is up", fg="green")


@app.command()
def down(scenario: ScenarioArg, set_: SetOpt = None, workdir: WorkdirOpt = DEFAULT_WORKDIR) -> None:
    """Stops the testbed and removes its containers and networks"""

    scn = _load(scenario, set_)
    testbed = Testbed(scn, workdir)
    testbed.down()


@app.command()
def status(scenario: ScenarioArg, set_: SetOpt = None, workdir: WorkdirOpt = DEFAULT_WORKDIR) -> None:
    """Lists the testbed's containers"""

    scn = _load(scenario, set_)
    testbed = Testbed(scn, workdir)
    rows = testbed.status()

    if not rows:
        typer.echo("not running")
        return

    for row in rows:
        typer.echo(f"{row['service']:<24} {row['role']:<10} {row['site']:<12} {row['ip']:<15} {row['state']}")


@app.command()
def netem(
    scenario: ScenarioArg,
    link: Annotated[str, typer.Argument(help="Link name")],
    latency: Annotated[str | None, typer.Option(help="One-way delay (e.g., 20ms)")] = None,
    jitter: Annotated[str | None, typer.Option(help="Delay variation (e.g., 2ms)")] = None,
    loss: Annotated[float | None, typer.Option(help="Loss in percent")] = None,
    rate: Annotated[str | None, typer.Option(help="Bandwidth (e.g., 10mbit)")] = None,
    set_: SetOpt = None,
    workdir: WorkdirOpt = DEFAULT_WORKDIR,
) -> None:
    """Changes a link's impairement on the running testbed"""

    scn = _load(scenario, set_)
    testbed = Testbed(scn, workdir)

    try:
        spec = testbed.set_link(link, latency=latency, jitter=jitter, loss=loss, rate=rate)

    except (KeyError, ValidationError) as e:
        typer.secho(str(e), fg="red", err=True)
        raise Exit(1) from None

    typer.echo(json.dumps(spec.model_dump(mode="json")))


if __name__ == "__main__":
    app()
