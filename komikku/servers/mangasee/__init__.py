# -*- coding: utf-8 -*-

# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from bs4 import BeautifulSoup
import json
import requests

from komikku.servers import convert_date_string
from komikku.servers import get_buffer_mime_type
from komikku.servers import Server
from komikku.servers import USER_AGENT
from komikku.utils import log_error_traceback

#
# MangaSee and MangaLife share exact same content
# MangaSee is the main site, MangaLife is a clone instance used to test new code
#

headers = {
    'User-Agent': USER_AGENT,
    'Origin': 'https://mangasee123.com',
}


class Mangasee(Server):
    id = 'mangasee'
    name = 'MangaSee'
    lang = 'en'

    base_url = 'https://mangasee123.com'
    search_url = base_url + '/search/'
    manga_url = base_url + '/manga/{0}'
    chapter_url = base_url + '/read-online/{0}-chapter-{1}-page-1.html'
    cover_url = 'https://cover.nep.li/cover/{0}.jpg'

    mangas = None

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = headers

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],  # not available
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=self.cover_url.format(data['slug']),
        ))

        soup = BeautifulSoup(r.content, 'lxml')

        data['name'] = soup.find('h1').text.strip()

        for li_element in soup.find('ul', class_='list-group list-group-flush').find_all('li'):
            if li_element.span is None:
                continue

            label = li_element.span.text.strip()
            li_element.span.extract()

            if label.startswith('Author'):
                data['authors'] = [artist.strip() for artist in li_element.text.split(',')]

            elif label.startswith('Genre'):
                data['genres'] = [genre.strip() for genre in li_element.text.split(',')]

            elif label.startswith('Status'):
                for status in li_element.text.split(','):
                    if 'Scan' not in status:
                        continue

                    status = status.replace('(Scan)', '').strip().lower()
                    if status in ('complete', 'hiatus', 'ongoing', ):
                        data['status'] = status
                    elif status in ('cancelled', 'discontinued', ):
                        data['status'] = 'suspended'
                    break

            elif label.startswith('Description'):
                data['synopsis'] = li_element.text.strip()

        # Chapters
        chapters = None
        try:
            script = soup.find_all('script')[-2].string
            if script:
                for line in script.split('\n'):
                    line = line.strip()
                    if not line.startswith('vm.Chapters'):
                        continue

                    chapters = json.loads(line.split('=')[1].strip()[:-1])
                    break
        except Exception as e:
            log_error_traceback(e)
            return None

        if chapters is not None:
            for chapter in reversed(chapters):
                slug = chapter['Chapter']

                title = f'{chapter["Type"]} {int(chapter["Chapter"][1:-1])}'
                if chapter['Chapter'][-1] != '0':
                    title = f'{title}.{chapter["Chapter"][-1]}'
                if chapter.get('ChapterName'):
                    title = f'{title} - {chapter["ChapterName"]}'

                data['chapters'].append(dict(
                    slug=slug,
                    title=title,
                    date=convert_date_string(chapter['Date'], '%Y-%m-%d %H:%M:%S') if chapter.get('Date') else None,
                ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data

        Currently, only pages are expected.
        """
        slug = int(chapter_slug[1:-1])
        if chapter_slug[-1] != '0':
            slug = f'{slug}.{chapter_slug[-1]}'
        if chapter_slug[0] != '1':
            slug = f'{slug}-index-{chapter_slug[0]}'

        r = self.session_get(self.chapter_url.format(manga_slug, slug))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.content, 'lxml')

        chapter = None
        domain = None
        try:
            script = soup.find_all('script')[-2].string
            if script:
                for line in script.split('\n'):
                    line = line.strip()
                    if not line.startswith('vm.CurChapter') and not line.startswith('vm.CurPathName'):
                        continue

                    if line.startswith('vm.CurChapter'):
                        chapter = json.loads(line.split('=')[1].strip()[:-1])
                    elif line.startswith('vm.CurPathName'):
                        domain = line.split('=')[1].strip()[1:-2]

                    if chapter is not None and domain is not None:
                        break
        except Exception as e:
            log_error_traceback(e)
            return None

        if chapter is None or domain is None:
            return None

        image_prefix = chapter_slug[1:-1]
        if chapter['Directory']:
            image_prefix = f'{chapter["Directory"]}/{image_prefix}'

        data = dict(
            pages=[],
        )
        for index in range(int(chapter['Page'])):
            data['pages'].append(dict(
                slug=None,
                image='https://{0}/manga/{1}/{2}-{3:03d}.png'.format(domain, manga_slug, image_prefix, index + 1),
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content"""
        r = self.session_get(page['image'])
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=page['image'].split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """ Returns manga absolute URL """
        return self.manga_url.format(slug)

    def get_most_populars(self):
        """ Returns most popular mangas list"""
        if self.mangas is None:
            r = self.session_get(self.search_url)
            if r.status_code != 200:
                return None

            mime_type = get_buffer_mime_type(r.content)
            if mime_type != 'text/html':
                return None

            soup = BeautifulSoup(r.content, 'lxml')

            try:
                script = soup.find_all('script')[-2].string
                if script:
                    for line in script.split('\n'):
                        line = line.strip()
                        if not line.startswith('vm.Directory'):
                            continue

                        self.mangas = json.loads(line.split('vm.Directory = ')[1].strip()[:-1])
                        break
            except Exception as e:
                log_error_traceback(e)
                return None

        if self.mangas is None:
            return None

        self.mangas = sorted(self.mangas, key=lambda m: m['v'], reverse=True)

        results = []
        for manga in self.mangas[:100]:
            results.append(dict(
                name=manga['s'],
                slug=manga['i'],
            ))

        return results

    def search(self, term):
        results = []
        term = term.lower()

        if self.mangas is None:
            if self.get_most_populars() is None:
                return None

        for manga in self.mangas:
            if term not in manga['s'].lower():
                continue

            results.append(dict(
                name=manga['s'],
                slug=manga['i'],
            ))

        return results


class Mangalife(Mangasee):
    id = 'mangalife:mangasee'
    name = 'MangaLife'
    lang = 'en'
    status = 'disabled'

    base_url = 'https://manga4life.com'
    search_url = base_url + '/search/'
    manga_url = base_url + '/manga/{0}'
    chapter_url = base_url + '/read-online/{0}-chapter-{1}-page-1.html'
