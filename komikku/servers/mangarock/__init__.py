# -*- coding: utf-8 -*-

# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import cloudscraper
from datetime import datetime
import json

from komikku.servers import convert_mri_data_to_webp_buffer
from komikku.servers import get_buffer_mime_type
from komikku.servers import Server
from komikku.servers import USER_AGENT

SERVER_NAME = 'Manga Rock'

headers = {
    'User-Agent': USER_AGENT,
    'Origin': 'https://mangarock.com',
}

#
# BEWARE: This server is disabled
# Dead since 01/2020
#


class Mangarock(Server):
    id = 'mangarock'
    name = SERVER_NAME
    lang = 'en'
    status = 'disabled'

    base_url = 'https://mangarock.com'
    api_url = 'https://api.mangarockhd.com/query/web401'
    api_search_url = api_url + '/mrs_search?country='
    api_most_populars_url = api_url + '/mrs_latest'
    api_manga_url = api_url + '/info?oid={0}&last=0'
    # api_chapter_url = api_url + '/pages?oid={0}'
    api_chapter_url = api_url + '/pagesv2?oid={0}'
    manga_url = base_url + '/manga/{0}'

    def __init__(self):
        if self.session is None:
            self.session = cloudscraper.create_scraper()
            self.session.headers.update(headers)

    def get_manga_data(self, initial_data):
        """
        Returns manga data from API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        r = self.session_get(self.api_manga_url.format(initial_data['slug']))
        if r is None:
            return None

        try:
            res = r.json()
        except json.decoder.JSONDecodeError:
            return None

        if res['code'] != 0:
            return None

        res = res['data']

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        # Name & cover
        data['name'] = res['name']
        data['cover'] = res['thumbnail']

        # Details & Synopsis
        for author in res['authors'] or []:
            data['authors'].append('{0} ({1})'.format(author['name'], author['role']))

        for genre in res['rich_categories'] or []:
            data['genres'].append(genre['name'])

        data['status'] = 'complete' if res['completed'] else 'ongoing'

        data['synopsis'] = res['description']

        # Chapters
        for chapter in res['chapters']:
            data['chapters'].append(dict(
                slug=chapter['oid'],
                title=chapter['name'],
                date=datetime.fromtimestamp(chapter['updatedAt']).date(),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data

        Currently, only pages are expected.
        """
        r = self.session_get(self.api_chapter_url.format(chapter_slug))
        if r is None:
            return None

        try:
            res = r.json()
        except json.decoder.JSONDecodeError:
            return None

        data = dict(
            pages=[],
            scrambled=0,
        )

        if res['code'] == 0:
            for page in res['data']:
                data['pages'].append(dict(
                    slug=None,  # not necessary, we know image url already
                    image=page['url'],
                ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        r = self.session_get(page['image'])
        if r is None or r.status_code != 200:
            return None

        buffer = r.content
        mime_type = get_buffer_mime_type(buffer)
        if mime_type == 'application/octet-stream':
            buffer = convert_mri_data_to_webp_buffer(buffer)
            mime_type = get_buffer_mime_type(buffer)

        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=buffer,
            mime_type=mime_type,
            name=page['image'].split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """ Returns manga absolute URL """
        return self.manga_url.format(slug)

    def get_most_populars(self):
        """ Returns full list of manga sorted by rank """
        r = self.session_post(self.api_most_populars_url)
        if r is None or r.status_code != 200:
            return None

        try:
            res = r.json()
        except json.decoder.JSONDecodeError:
            return None

        if res['code'] != 0:
            return None

        # Sort by rank
        res = sorted(res['data'], key=lambda i: i['rank'])

        results = []
        for item in res:
            results.append(dict(
                name=item['name'],
                slug=item['oid'],
            ))

        return results

    def search(self, term):
        r = self.session_post(self.api_search_url, json={'type': 'series', 'keywords': term})
        if r is None or r.status_code != 200:
            return None

        try:
            res = r.json()
        except json.decoder.JSONDecodeError:
            return None

        if res['code'] != 0:
            return None

        # Returned data for each manga:
        # oid: slug of the manga
        results = []
        for oid in res['data']:
            data = self.get_manga_data(dict(slug=oid))
            if data:
                results.append(dict(
                    name=data['name'],
                    slug=data['slug'],
                ))

        return results
