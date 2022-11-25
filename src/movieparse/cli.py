"""A one line summary of the module or program, terminated by a period.

Leave one blank line.  The rest of this docstring should contain an
overall description of the module or program.  Optionally, it may also
contain a brief description of exported classes and functions and/or usage
examples.

Typical usage example:

foo = ClassFoo()
bar = foo.FunctionBar()
"""

import argparse
import pathlib

from movieparse.main import Movieparse


def main() -> None:
    """Entrypoint for CLI."""
    parser = argparse.ArgumentParser(prog="tmdb_parser")

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--root_movie_dir",
        nargs="?",
        type=pathlib.Path,
        help="Directory containing your movie folders.",
    )
    group.add_argument(
        "--movie_list",
        nargs="+",
        type=str,
        help="Alternative to root_movie_dir, takes list of strings with movie title and optionally movie release year.",
    )
    parser.add_argument(
        "--tmdb_api_key",
        nargs="?",
        type=str,
        help="TMDB API key. If not supplied here, environment variable TMDB_API_KEY will be read.",
    )
    parser.add_argument(
        "--parsing_style",
        nargs="?",
        type=int,
        choices=[0, max(Movieparse.get_parsing_patterns().keys())],
        default=-1,
        help="Naming convention used - see documentation for examples.",
    )
    parser.add_argument(
        "--output_dir",
        nargs="?",
        type=pathlib.Path,
        help="Directory where output CSVs get written to. Defaults to current directory.",
    )
    parser.add_argument(
        "--lax",
        action="store_false",
        help="Use if TMDB ID lookup should fall back to title only (instead of year+title). Results may not be as accurate.",
    )
    parser.add_argument(
        "--language",
        nargs="?",
        type=str,
        const="en_US",
        default="en_US",
        help="ISO-639-1 language shortcode for specifying result language. Defaults to en_US.",
    )

    args = parser.parse_args()

    m = Movieparse(
        output_dir=args.output_dir,
        tmdb_api_key=args.tmdb_api_key,
        parsing_style=args.parsing_style,
        strict=args.lax,
        language=args.language,
    )

    if args.root_movie_dir is not None:
        m.parse_root_movie_dir(args.root_movie_dir)
    elif args.movie_list is not None:
        m.parse_movielist(args.movie_list)
    m.write()


if __name__ == "__main__":
    main()
