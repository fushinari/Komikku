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

SERVER_NAME = 'Union Mangás'


class Unionmangas(Server):
    id = 'unionmangas'
    name = SERVER_NAME
    lang = 'pt'
    long_strip_genres = ['Webtoon', ]

    base_url = 'https://unionmangas.top'
    api_search_url = base_url + '/assets/busca.php?q={0}'
    most_populars_url = base_url + '/lista-mangas/visualizacoes'
    manga_url = base_url + '/perfil-manga/{0}'
    chapter_url = base_url + '/leitor/{0}/{1}'
    image_url = base_url + '/leitor/mangas/{0}/{1}/{2}'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'user-agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """ Returns manga data by scraping manga HTML page content """
        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

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

        container_element = soup.find('div', class_='tamanho-bloco-perfil')

        data['name'] = container_element.find('h2').text.strip()
        data['cover'] = container_element.find('img', class_='img-thumbnail').get('src')

        for div_element in container_element.find_all('div', class_='col-md-8 col-xs-12'):
            if not div_element.h4:
                continue

            label = div_element.find('label').text.strip()
            div_element.h4.label.extract()
            value = div_element.text.strip()

            if label.startswith('Gênero'):
                data['genres'] = [genre.strip() for genre in value.split(',')]
            elif label.startswith(('Autor', 'Artista')):
                for author in value.split(','):
                    author = author.strip()
                    if author not in data['authors']:
                        data['authors'].append(author)
            elif label.startswith('Status'):
                if value == 'Completo':
                    data['status'] = 'complete'
                elif value == 'Ativo':
                    data['status'] = 'ongoing'

        data['synopsis'] = container_element.find('div', class_='panel-body').text.strip()

        # Chapters
        for div_element in reversed(container_element.find_all('div', class_='row lancamento-linha')):
            a_element = div_element.div.a
            span_element = div_element.div.find_all('span', recursive=False)[1]

            data['chapters'].append(dict(
                title=a_element.text.strip(),
                slug=a_element.get('href').split('/')[-1],
                date=convert_date_string(span_element.text.strip()[1:-1], format='%d/%m/%Y'),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """ Returns manga chapter data by scraping chapter HTML page content """
        manga_slug = manga_name.replace(' ', '_')

        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if 'leitor' not in r.url:
            # Chapter page doesn't exist, we have been redirected to manga page
            return None
        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        data = dict(
            pages=[],
        )

        for img_element in soup.find_all('img', class_='img-manga'):
            url = img_element.get('src')
            if f'{manga_name}/{chapter_slug}' not in url:
                continue

            data['pages'].append(dict(
                slug=None,
                image=url.split('/')[-1],
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        r = self.session_get(self.image_url.format(manga_name, chapter_slug, page['image']))
        if r is None or r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=page['image'],
        )

    def get_manga_url(self, slug, url):
        """ Returns manga absolute URL """
        return self.manga_url.format(slug)

    def get_most_populars(self):
        r = self.session_get(self.most_populars_url)
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for div_element in soup.find_all('div', class_='bloco-manga'):
            a_element = div_element.find_all('a', recursive=False)[1]

            results.append(dict(
                name=a_element.text.strip(),
                slug=a_element.get('href').split('/')[-1],
            ))

        return results

    def search(self, term=None):
        r = self.session_post(self.api_search_url.format(term))
        if r is None or r.status_code != 200:
            return None

        try:
            res = r.json()
        except json.decoder.JSONDecodeError:
            return None

        results = []
        for item in res['items']:
            results.append(dict(
                name=item['titulo'],
                slug=item['url'],
            ))

        return results
