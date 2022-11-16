import os
import pathlib
import re
from typing import Dict, List, Optional, Set, Union

import pandas as pd
import requests
from tqdm import tqdm


class movieparse:
    mapping = pd.DataFrame()
    cast = collect = crew = details = genres = prod_comp = prod_count = spoken_langs = pd.DataFrame()
    cached_mapping_ids: Set[int] = set()
    cached_metadata_ids: Set[int] = set()
    cached_mapping = pd.DataFrame()

    # default codes
    __DEFAULT = 0
    __NO_RESULT = -1
    __NO_EXTRACT = -2
    __BAD_RESPONSE = -3

    @staticmethod
    def get_parsing_patterns() -> dict[int, re.Pattern[str]]:
        return {
            0: re.compile(r"^(?P<disk_year>\d{4})\s{1}(?P<disk_title>.+)$"),
            1: re.compile(r"^(?P<disk_year>\d{4})\s-\s(?P<disk_title>.+)$"),
        }

    def __init__(
        self,
        output_path: pathlib.Path | None = None,
        tmdb_api_key: str | None = None,
        parsing_style: int = -1,
        eager: bool = False,
        strict: bool = False,
        language: str = "en_US",
    ):

        self.__EAGER = eager
        self.__STRICT = strict
        self.__LANGUAGE = language

        if output_path is None:
            output_path = pathlib.Path(os.getcwd())
        elif output_path.is_dir() is False:
            exit("please supply an OUTPUT_DIR that is a directory!")
        self.__OUTPUT_PATH = output_path

        if tmdb_api_key is None and os.getenv("TMDB_API_KEY") is not None:
            self.__TMDB_API_KEY = os.getenv("TMDB_API_KEY")
        elif tmdb_api_key is not None:
            self.__TMDB_API_KEY = tmdb_api_key
        else:
            exit("please supply a TMDB_API_KEY!")

        if parsing_style not in range(-1, max(movieparse.get_parsing_patterns().keys())):
            exit("please supply a valid PARSING_STYLE!")
        else:
            self.__PARSING_STYLE = parsing_style

        # setup internals
        self._setup_caches()
        self._read_existing()

    def _table_iter(self) -> dict[str, pd.DataFrame]:
        return {
            "cast": self.cast,
            "collection": self.collect,
            "crew": self.crew,
            "genres": self.genres,
            "production_companies": self.prod_comp,
            "production_countries": self.prod_count,
            "spoken_languages": self.spoken_langs,
            "details": self.details,
        }

    def _setup_caches(self) -> None:
        tmp_path = self.__OUTPUT_PATH / "mapping.csv"
        if tmp_path.exists():
            self.cached_mapping = pd.read_csv(tmp_path)
            self.cached_mapping_ids = set(self.cached_mapping["tmdb_id"])

    def _read_existing(self) -> None:
        """Reads metadata CSVs if existing and appends tmdb_ids to cached_metadata_ids."""
        df_list = []
        for fname, df in self._table_iter().items():
            tmp_path = self.__OUTPUT_PATH / f"{fname}.csv"
            if tmp_path.exists():
                df = pd.read_csv(tmp_path)
                df = self._assign_types(df)
                self.cached_metadata_ids |= set(df["tmdb_id"])
            else:
                df = pd.DataFrame()
            df_list.append(df)

        (
            self.cast,
            self.collect,
            self.crew,
            self.genres,
            self.prod_comp,
            self.prod_count,
            self.spoken_langs,
            self.details,
        ) = df_list

    def parse_movielist(self, movielist: List[str]) -> None:
        if not movielist:
            raise Exception("movielist can't be empty!")

        self.mapping = pd.DataFrame(
            {"tmdb_id": self.__DEFAULT, "tmdb_id_man": self.__DEFAULT, "input": movielist, "canonical_input": movielist}
        )

        self._generic_parse()

    def parse_root_movie_dir(self, root_movie_dir: pathlib.Path) -> None:
        if root_movie_dir.is_dir() is False:
            raise Exception("root_movie_dir has to a directory!")

        names = []
        for folder in root_movie_dir.iterdir():
            if folder.is_dir():
                names.append(folder)

        self.mapping = pd.DataFrame(
            {
                "tmdb_id": self.__DEFAULT,
                "tmdb_id_man": self.__DEFAULT,
                "input": names,
                "canonical_input": [x.name for x in names],
            }
        )

        self._generic_parse()

    def _generic_parse(self):
        if self.__PARSING_STYLE == -1:
            self._guess_parsing_style()

        self._update_mapping()
        self._get_ids()
        self._update_metadata_lookup_ids()
        self._get_metadata()

    def _guess_parsing_style(self) -> None:
        """Iterates over supplied names with all parsing styles, determining the most matches. Incase two patterns have
        the same matches, the first one is used."""

        tmp = self.mapping[["canonical_input"]].copy()
        max_matches = 0
        for style, pattern in movieparse.get_parsing_patterns().items():
            matches = tmp["canonical_input"].str.extract(pattern, expand=True).notnull().sum().sum()
            if matches > max_matches:
                self.__PARSING_STYLE = style
                max_matches = matches

        if max_matches == 0 and self.__PARSING_STYLE == -1:
            exit("couldn't estimate a parsing style, please supply one for yourself!")

        max_items = len(tmp.index) * 2
        print(f"estimated best parsing style: {self.__PARSING_STYLE} with {max_matches} / {max_items} matches")

    def _update_mapping(self) -> None:
        self.mapping = pd.concat([self.cached_mapping, self.mapping], axis=0, ignore_index=True).drop_duplicates(
            subset="canonical_input", keep="first"
        )

    def _get_id(self, title: str, year: int = -1) -> int:
        """Creates API request with title and year. If that fails,
        creates another with just the title (if STRICT=False).

        Returns -1 if no results come back.
        """
        if year != self.__NO_RESULT:
            response = requests.get(
                f"https://api.themoviedb.org/3/search/movie/?api_key={self.__TMDB_API_KEY}&query={title}&year={year}&include_adult=true"
            ).json()
            try:
                return int(response["results"][0]["id"])
            except IndexError:
                if self.__STRICT is True:
                    return self.__NO_RESULT
            except KeyError:
                return self.__BAD_RESPONSE

        response = requests.get(
            f"https://api.themoviedb.org/3/search/movie/?api_key={self.__TMDB_API_KEY}&query={title}&include_adult=true"
        ).json()
        try:
            return int(response["results"][0]["id"])
        except IndexError:
            return self.__NO_RESULT
        except KeyError:
            return self.__BAD_RESPONSE

    def _get_ids(self) -> None:
        def helper(canon_name: str, tmdb_id: int):
            if tmdb_id != self.__DEFAULT and not self.__EAGER:
                return tmdb_id

            regex = movieparse.get_parsing_patterns()[self.__PARSING_STYLE]
            extract = re.match(regex, canon_name)
            if extract is not None:
                year = int(extract.group("disk_year"))
                title = extract.group("disk_title")
                tmdb_id = self._get_id(title, year)
            else:
                tmdb_id = self.__NO_EXTRACT
            return tmdb_id

        self.mapping["tmdb_id"] = [
            helper(x, y)
            for x, y in tqdm(
                zip(self.mapping["canonical_input"], self.mapping["tmdb_id"]),
                total=len(self.mapping.index),
                desc="getting tmdb_ids",
            )
        ]

        self.mapping.to_csv((self.__OUTPUT_PATH / "mapping.csv"), date_format="%Y-%m-%d", index=False)

    def _update_metadata_lookup_ids(self) -> None:
        self.metadata_lookup_ids = set(self.mapping["tmdb_id"]) | set(self.mapping["tmdb_id_man"])

        if self.__EAGER is True:
            self.metadata_lookup_ids -= set(self.cached_metadata_ids)

        self.metadata_lookup_ids -= set([self.__DEFAULT, self.__NO_RESULT, self.__NO_EXTRACT, self.__BAD_RESPONSE])

    def _dissect_metadata_response(self, response: Dict[str, pd.DataFrame], tmdb_id: int) -> None:
        results = []
        for c, df in self._table_iter().items():
            tmp = pd.DataFrame()

            if c in ["cast", "crew"]:
                tmp = pd.json_normalize(response["credits"], record_path=c).add_prefix(f"{c}.")
            elif c == "collection":
                if response["belongs_to_collection"] is not None:
                    tmp = pd.json_normalize(response["belongs_to_collection"]).add_prefix(f"{c}.")
                response.pop("belongs_to_collection")
            elif c == "details":
                response.pop("credits")
                response.pop("id")
                tmp = pd.json_normalize(response)
            else:
                tmp = pd.json_normalize(response, record_path=c).add_prefix(f"{c}.")
                response.pop(c)

            tmp["tmdb_id"] = tmdb_id
            tmp = self._assign_types(tmp)

            if tmp.empty is False:
                first_column = tmp.pop("tmdb_id")
                tmp.insert(0, "tmdb_id", first_column)

                df = pd.concat([df, tmp], axis=0, ignore_index=True)
            results.append(df)
        (
            self.cast,
            self.collect,
            self.crew,
            self.genres,
            self.prod_comp,
            self.prod_count,
            self.spoken_langs,
            self.details,
        ) = results

    def _get_metadata(self) -> None:
        for tmdb_id in tqdm(self.metadata_lookup_ids, desc="getting metadata"):
            url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={self.__TMDB_API_KEY}&language={self.__LANGUAGE}&append_to_response=credits"
            response = requests.get(url).json()
            self._dissect_metadata_response(response, tmdb_id)

    def write(self) -> None:
        for fname, df in self._table_iter().items():
            tmp_path = self.__OUTPUT_PATH / f"{fname}.csv"
            if df.empty is False:
                df.to_csv(tmp_path, date_format="%Y-%m-%d", index=False)

    def _assign_types(self, df: pd.DataFrame) -> pd.DataFrame:
        types = {
            "tmdb_id": "int32",
            "tmdb_id_man": "int32",
            "cast.adult": bool,
            "cast.gender": "int8",
            "cast.id": int,
            "cast.known_for_department": "category",
            "cast.name": str,
            "cast.original_name": str,
            "cast.popularity": float,
            "cast.profile_path": str,
            "cast.cast_id": "int8",
            "cast.character": str,
            "cast.credit_id": str,
            "cast.order": "int8",
            "collection.id": int,
            "collection.name": str,
            "collection.poster_path": str,
            "collection.backdrop_path": str,
            "crew.adult": bool,
            "crew.gender": "int8",
            "crew.id": int,
            "crew.known_for_department": "category",
            "crew.name": str,
            "crew.original_name": str,
            "crew.popularity": float,
            "crew.profile_path": str,
            "crew.credit_id": str,
            "crew.department": "category",
            "crew.job": str,
            "genres.id": "int8",
            "genres.name": str,
            "production_companies.id": "int32",
            "production_companies.logo_path": str,
            "production_companies.name": "category",
            "production_companies.origin_country": "category",
            "production_countries.iso_3166_1": "category",
            "production_countries.name": str,
            "spoken_languages.english_name": "category",
            "spoken_languages.iso_3166_1": "category",
            "spoken_languages.name": str,
            "adult": bool,
            "backdrop_path": str,
            "budget": int,
            "homepage": str,
            "imdb_id": str,
            "original_language": "category",
            "original_title": str,
            "overview": str,
            "popularity": float,
            "poster_path": str,
            "release_date": "datetime64[ns]",
            "revenue": int,
            "runtime": "int16",
            "status": "category",
            "tagline": str,
            "title": str,
            "video": bool,
            "vote_average": float,
            "vote_count": "int16",
        }

        for k, v in types.items():
            try:
                df[k] = df[k].astype(v)
            except KeyError:
                pass

        return df
