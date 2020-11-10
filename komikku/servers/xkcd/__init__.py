# -*- coding: utf-8 -*-

# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from bs4 import BeautifulSoup
import requests
import textwrap

from komikku.servers import convert_date_string
from komikku.servers import get_buffer_mime_type
from komikku.servers import Server
from komikku.servers import USER_AGENT

SERVER_NAME = 'xkcd'


class Xkcd(Server):
    id = 'xkcd'
    name = SERVER_NAME
    lang = 'en'

    base_url = 'https://www.xkcd.com'
    manga_url = base_url + '/archive/'
    chapter_url = base_url + '/{0}/info.0.json'
    image_url = 'https://imgs.xkcd.com/comics/{0}'
    cover_url = base_url + '/s/0b7742.png'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'user-agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """ Returns manga data by scraping manga HTML page content """
        r = self.session_get(self.manga_url)
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        data = initial_data.copy()
        data.update(dict(
            authors=['Randall Munroe', ],
            scanlators=[],
            genres=[],
            status='ongoing',
            synopsis='A webcomic of romance, sarcasm, math, and language.',
            chapters=[],
            server_id=self.id,
            cover=self.cover_url,
        ))

        # Chapters
        for a_element in reversed(soup.find('div', id='middleContainer').find_all('a')):
            slug = a_element.get('href')[1:-1]

            data['chapters'].append(dict(
                slug=slug,
                date=convert_date_string(a_element.get('title'), '%Y-%m-%d'),
                title='{0} - {1}'.format(slug, a_element.text.strip()),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(chapter_slug))
        if r is None:
            return None

        try:
            data = r.json()
        except Exception:
            return None

        url_image = data['img']
        # The comic passed in HD after Chapter 1084
        if int(chapter_slug) >= 1084 and int(chapter_slug) not in (1097, 2042, 2202, ):
            url_image = url_image.replace('.png', '_2x.png')

        return dict(
            pages=[
                dict(
                    slug=None,
                    image=url_image.split('/')[-1],
                ),
                dict(
                    slug=None,
                    image=None,
                    text=data['alt'],
                )
            ]
        )

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        if page.get('image'):
            r = self.session_get(self.image_url.format(page['image']))
            name = page['image']
        else:
            r = self.session_get(
                'https://fakeimg.pl/1500x2126/ffffff/000000/',
                params=dict(
                    text='\n'.join(textwrap.wrap(page['text'], 25)),
                    font_size=64,
                    font='museo'
                )
            )
            name = '{0}-alt-text.png'.format(chapter_slug)

        if r is None or r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=name,
        )

    def get_manga_url(self, slug, url):
        """ Returns manga absolute URL """
        return self.manga_url

    def get_most_populars(self):
        return self.search()

    @staticmethod
    def search(term=None):
        return [dict(
            slug='',
            name='xkcd',
        )]
