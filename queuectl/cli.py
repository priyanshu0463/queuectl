import typer

app=typer.Typer(help="QueueCTL- Simple Job QUEUE CLI")

@app.command()
def hello(name:str = typer.Argument(...,help="Name to greet")):
	"""Say hello"""
	typer.echo(f"Hello, {name}!")
if __name__ == "__main__":
	app()
