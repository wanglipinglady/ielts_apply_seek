"""W10 调研：click multi-command 调用顺序验证。"""
import click
import os
from click.testing import CliRunner


@click.group()
@click.option("--mode")
@click.pass_context
def cli(ctx, mode):
    click.echo(f"[CLI_ENTRY] cli() called, mode={mode}")
    click.echo(f"[CLI_ENTRY] env before write = {os.environ.get('IB_MODE')!r}")
    if mode:
        os.environ["IB_MODE"] = mode
    click.echo(f"[CLI_ENTRY] cli() about to return, env={os.environ.get('IB_MODE')!r}")


@cli.result_callback()
def result_callback(result, **kwargs):
    click.echo(f"[RESULT_CALLBACK] env={os.environ.get('IB_MODE')!r}")


@cli.command()
def sub():
    click.echo(f"[SUB] env={os.environ.get('IB_MODE')!r}")


print("--- Test 1: --mode online, no env set ---")
r = CliRunner().invoke(cli, ["--mode", "online", "sub"])
print(r.output)

print("--- Test 2: --mode online, env already set ---")
os.environ["IB_MODE"] = "PREEXISTING"
r = CliRunner().invoke(cli, ["--mode", "online", "sub"])
print(r.output)
del os.environ["IB_MODE"]
