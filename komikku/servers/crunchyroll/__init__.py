import logging

from komikku.servers import convert_date_string
from komikku.servers import get_buffer_mime_type
from komikku.servers import Server
from komikku.servers import USER_AGENT

SERVER_NAME = 'Crunchyroll'

logger = logging.getLogger('komikku.servers.crunchyroll')


class Crunchyroll(Server):
    id = 'crunchyroll'
    name = SERVER_NAME
    lang = 'en'
    locale = 'enUS'
    has_login = True
    session_expiration_cookies = ['session_id', ]

    base_url = 'https://www.crunchyroll.com'
    manga_url = base_url + '/comics/manga/{0}/volumes'

    start_session_url = 'https://api.crunchyroll.com/start_session.0.json'
    login_url = 'https://api.crunchyroll.com/login.0.json'

    api_base_url = 'https://api-manga.crunchyroll.com'
    api_auth_url = api_base_url + '/cr_authenticate?auth=&session_id={}&version=0&format=json'
    api_series_url = api_base_url + '/series?sort=popular'
    api_chapter_url = api_base_url + '/list_chapter?session_id={}&chapter_id={}&auth={}'
    api_chapters_url = api_base_url + '/chapters?series_id={}'

    api_auth_token = None
    api_session_id = None
    possible_page_url_keys = ['encrypted_mobile_image_url', 'encrypted_composed_image_url']
    page_url_key = possible_page_url_keys[0]

    _access_token = 'WveH9VkPLrXvuNm'
    _access_type = 'com.crunchyroll.crunchyroid'

    headers = {
        'User-Agent': USER_AGENT,
        'Origin': 'https://www.crunchyroll.com',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en,en-US;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
    }

    def __init__(self, username=None, password=None):
        self.init(username, password)

    def _get_session_id(self):
        if 'session_id' in self.session.cookies:
            self.api_session_id = self.session.cookies['session_id']
            return

        data = self.session_post(
            self.start_session_url,
            data={
                'device_id': '1234567',
                'device_type': self._access_type,
                'access_token': self._access_token,
            }
        ).json()['data']
        self.api_session_id = data['session_id']

    @staticmethod
    def decode_image(buffer):
        # Don't know why 66 is special
        return bytes(b ^ 66 for b in buffer)

    def get_manga_data(self, initial_data):
        """
        Returns manga data from API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'
        r = self.session_get(self.api_chapters_url.format(initial_data['slug']))

        json_data = r.json()
        if 'error' in json_data:
            logger.warning('Manga slug {0}: {1}'.format(initial_data['slug'], json_data['error']['msg']))
            return None

        resp_data = json_data['series']
        chapters = json_data['chapters']

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],
            genres=[],
            status='ongoing',
            chapters=[],
            synopsis=resp_data['locale'][self.locale]['description'],
            server_id=self.id,
            cover=resp_data['locale'][self.locale]['thumb_url'],
            url=self.manga_url.format(resp_data['url'][1:]),
        ))

        if resp_data.get('authors'):
            data['authors'] += [t.strip() for t in resp_data['authors'].split(',')]
        if resp_data.get('artist'):
            data['authors'] += [t.strip() for t in resp_data['artist'].split(',') if t.strip() not in data['authors']]

        if resp_data.get('translator'):
            data['scanlators'] += [t.strip() for t in resp_data['translator'].split('|')]

        if resp_data.get('genres'):
            data['genres'] = resp_data['genres']

        if resp_data['locale'][self.locale].get('copyright'):
            data['synopsis'] += '\n\n' + resp_data['locale'][self.locale]['copyright']

        # Chapters
        for chapter in chapters:
            date = None
            if chapter.get('availability_start'):
                date_string = chapter['availability_start'].split(' ')[0]
                if len(date_string) == 10 and '-00' not in date_string:
                    date = convert_date_string(date_string, '%Y-%m-%d')
            if date is None and chapter.get('updated'):
                date_string = chapter['updated'].split(' ')[0]
                if len(date_string) == 10 and '-00' not in date_string:
                    date = convert_date_string(date_string, '%Y-%m-%d')

            data['chapters'].append(dict(
                slug=chapter['chapter_id'],
                title=chapter['locale'][self.locale]['name'],
                date=date,
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data

        Currently, only pages are expected.
        """
        if self.logged_in and (self.api_session_id is None or self.api_auth_token is None):
            if not self.init_api():
                return None

        r = self.session_get(self.api_chapter_url.format(self.api_session_id, chapter_slug, self.api_auth_token))

        resp_data = r.json()
        if resp_data is None or resp_data.get('error', False):
            # We aren't logged in
            return None

        pages = resp_data['pages']
        pages.sort(key=lambda x: int(x['number']))

        data = dict(
            pages=[],
        )

        for page in pages:
            data['pages'].append(dict(
                slug=None,
                image=page['locale'][self.locale][self.page_url_key],
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        r = self.session_get(page['image'])
        if r.status_code != 200:
            return None

        buffer = self.decode_image(r.content)

        mime_type = get_buffer_mime_type(buffer)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=buffer,
            mime_type=mime_type,
            name=page['image'].split('/')[-1],
        )

    @staticmethod
    def get_manga_url(slug, url):
        """ Returns manga absolute URL """
        return url

    def get_most_populars(self):
        """ Returns full list of manga sorted by rank """
        r = self.session_get(self.api_series_url)

        result = []

        resp_data = r.json()
        resp_data.sort(key=lambda x: not x['featured'])

        for item in resp_data:
            if 'locale' not in item:
                continue

            result.append({
                'slug': item['series_id'],
                'name': item['locale'][self.locale]['name'],
            })

        return result

    def init_api(self):
        """ Retrieves API session ID and authentication token """
        self._get_session_id()
        r = self.session_get(self.api_auth_url.format(self.api_session_id))
        data = r.json()

        if 'data' in data:
            self.api_auth_token = ''.join(data['data']['auth'])
            return True

        return False

    def login(self, username, password):
        """ Log in and initializes API """
        if not username or not password:
            return False
        self._get_session_id()

        login = self.session_post(
            self.login_url,
            data={
                'session_id': self.api_session_id,
                'account': username,
                'password': password
            }
        ).json()

        if 'data' in login:
            self.api_auth_token = login['data']['auth']
            self.save_session()
            return True

        return False

    def search(self, term):
        return filter(lambda x: term.lower() in x['name'].lower(), self.get_most_populars())
