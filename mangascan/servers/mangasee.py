# -*- coding: utf-8 -*-

# Copyright (C) 2019 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from bs4 import BeautifulSoup
import magic
import requests
from requests.exceptions import ConnectionError

from mangascan.servers import user_agent

server_id = 'mangasee'
server_name = 'MangaSee'
server_lang = 'en'

session = None


class Mangasee():
    id = server_id
    name = server_name
    lang = server_lang

    base_url = 'https://mangaseeonline.us'
    search_url = base_url + '/search/request.php'
    manga_url = base_url + '/manga/{0}'
    chapter_url = base_url + '/read-online/{0}-chapter-{1}-page-1.html'
    page_url = base_url + '/read-online/{0}-chapter-{1}-page-{2}.html'
    cover_url = 'https://static.mangaboss.net/cover/{0}'

    def __init__(self):
        global session

        if session is None:
            session = requests.Session()
            session.headers.update({'user-agent': user_agent})

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        try:
            r = session.get(self.manga_url.format(initial_data['slug']))
        except ConnectionError:
            return None

        mime_type = magic.from_buffer(r.content[:128], mime=True)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            cover=None,
            server_id=self.id,
        ))

        # Name & cover
        data['name'] = soup.find('h1', class_='SeriesName').text.strip()
        data['cover'] = soup.find('div', class_='leftImage').img.get('src').split('/')[-1]

        # Details & Synopsis
        elements = soup.find('span', class_='details').find_all('div', class_='row')
        for element in elements:
            div_element = element.div
            if div_element.b:
                label = div_element.b.text.strip()
            elif div_element.strong:
                label = div_element.strong.text.strip()

            if label.startswith('Author'):
                links_elements = div_element.find_all('a')
                for link_element in links_elements:
                    data['authors'].append(link_element.text.strip())
            elif label.startswith('Genre'):
                links_elements = div_element.find_all('a')
                for link_element in links_elements:
                    data['genres'].append(link_element.text.strip())
            elif label.startswith('Status'):
                # possible values: ongoing, complete, None
                value = div_element.find_all('a')[0].text.strip()
                if value.startswith('Complete'):
                    data['status'] = 'complete'
                elif value.startswith('Ongoing'):
                    data['status'] = 'ongoing'
            elif label.startswith('Description'):
                data['synopsis'] = div_element.div.text.strip()

        # Chapters
        elements = soup.find('div', class_='chapter-list').find_all('a', recursive=False)
        for link_element in reversed(elements):
            data['chapters'].append(dict(
                slug=link_element.get('chapter'),
                date=link_element.time.text.strip(),
                title=link_element.span.text.strip(),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        url = self.chapter_url.format(manga_slug, chapter_slug)

        try:
            r = session.get(url)
        except ConnectionError:
            return None

        mime_type = magic.from_buffer(r.content[:128], mime=True)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        options_elements = soup.find('select', class_='PageSelect').find_all('option')

        data = dict(
            pages=[],
        )
        for option_element in options_elements:
            data['pages'].append(dict(
                slug=option_element.get('value'),
                image=None,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """
        Returns chapter page scan (image) content
        """
        url = self.page_url.format(manga_slug, chapter_slug, page['slug'])
        try:
            r = session.get(url)
        except ConnectionError:
            return (None, None)

        soup = BeautifulSoup(r.text, 'html.parser')

        image_url = soup.find('img', class_='CurImage').get('src')
        try:
            r = session.get(image_url)
        except ConnectionError:
            return (None, None)

        mime_type = magic.from_buffer(r.content[:128], mime=True)

        return (image_url.split('/')[-1], r.content) if r.status_code == 200 and mime_type.startswith('image') else (None, None)

    def get_manga_cover_image(self, cover_path):
        """
        Returns manga cover (image) content
        """
        try:
            r = session.get(self.cover_url.format(cover_path))
        except ConnectionError:
            return None

        mime_type = magic.from_buffer(r.content[:128], mime=True)

        return r.content if r.status_code == 200 and mime_type.startswith('image') else None

    def get_manga_url(self, slug, url):
        """
        Returns manga absolute URL
        """
        return self.manga_url.format(slug)

    def search(self, term):
        try:
            r = session.post(self.search_url, data=dict(keyword=term, page=1))
        except ConnectionError:
            return None

        if r.status_code == 200:
            soup = BeautifulSoup(r.content, 'html.parser')

            results = []
            for element in soup.find_all('div', class_='requested'):
                link_element = element.find('a', class_='resultLink')

                results.append(dict(
                    slug=link_element.get('href').split('/')[-1],
                    name=link_element.text.strip(),
                ))

            return results
        else:
            return None