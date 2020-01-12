# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from gettext import gettext as _
import importlib
import json
import os
import sqlite3
import shutil

from gi.repository import GLib

from komikku.servers import unscramble_image

VERSION = 1


def adapt_json(data):
    return (json.dumps(data, sort_keys=True)).encode()


def convert_json(blob):
    return json.loads(blob.decode())


sqlite3.register_adapter(dict, adapt_json)
sqlite3.register_adapter(list, adapt_json)
sqlite3.register_adapter(tuple, adapt_json)
sqlite3.register_converter('json', convert_json)


def backup_db():
    db_path = get_db_path()
    if os.path.exists(db_path) and check_db():
        print('Save a DB backup')
        shutil.copyfile(db_path, get_db_backup_path())


def check_db():
    db_conn = create_db_connection()

    if db_conn:
        res = db_conn.execute('PRAGMA integrity_check').fetchone()  # PRAGMA quick_check

        fk_violations = len(db_conn.execute('PRAGMA foreign_key_check').fetchall())

        db_conn.close()

        return res[0] == 'ok' and fk_violations == 0

    return False


def create_db_connection():
    con = sqlite3.connect(get_db_path(), detect_types=sqlite3.PARSE_DECLTYPES)
    if con is None:
        print("Error: Can not create the database connection.")
        return None

    con.row_factory = sqlite3.Row
    return con


def create_table(conn, sql):
    try:
        c = conn.cursor()
        c.execute(sql)
    except Exception as e:
        print('SQLite-error:', e)


def get_data_dir():
    return GLib.get_user_data_dir()


def get_db_path():
    return os.path.join(get_data_dir(), 'komikku.db')


def get_db_backup_path():
    return os.path.join(get_data_dir(), 'komikku_backup.db')


def init_db():
    db_path = get_db_path()
    db_backup_path = get_db_backup_path()
    if os.path.exists(db_path) and os.path.exists(db_backup_path) and not check_db():
        # Restore backup
        print('Restore DB from backup')
        shutil.copyfile(db_backup_path, db_path)

    sql_create_mangas_table = """CREATE TABLE IF NOT EXISTS mangas (
        id integer PRIMARY KEY,
        slug text NOT NULL,
        url text, -- only used in case slug can't be used to forge the url
        server_id text NOT NULL,
        name text NOT NULL,
        authors json,
        scanlators json,
        genres json,
        synopsis text,
        status text,
        sort_order text,
        reading_direction text,
        background_color text,
        scaling text,
        last_read timestamp,
        last_update timestamp,
        UNIQUE (slug, server_id)
    );"""

    sql_create_chapters_table = """CREATE TABLE IF NOT EXISTS chapters (
        id integer PRIMARY KEY,
        manga_id integer REFERENCES mangas(id) ON DELETE CASCADE,
        slug text NOT NULL,
        url text, -- only used in case slug can't be used to forge the url
        title text NOT NULL,
        pages json,
        scrambled integer,
        date date,
        rank integer NOT NULL,
        downloaded integer NOT NULL,
        recent integer NOT NULL,
        read integer NOT NULL,
        last_page_read_index integer,
        UNIQUE (slug, manga_id)
    );"""

    sql_create_downloads_table = """CREATE TABLE IF NOT EXISTS downloads (
        id integer PRIMARY KEY,
        chapter_id integer REFERENCES chapters(id) ON DELETE CASCADE,
        status text NOT NULL,
        percent float NOT NULL,
        date timestamp NOT NULL,
        UNIQUE (chapter_id)
    );"""

    db_conn = create_db_connection()
    if db_conn is not None:
        create_table(db_conn, sql_create_mangas_table)
        create_table(db_conn, sql_create_chapters_table)
        create_table(db_conn, sql_create_downloads_table)

        db_conn.execute('PRAGMA user_version = {0}'.format(VERSION))
        print('DB version', db_conn.execute('PRAGMA user_version').fetchone()[0])

        db_conn.close()


def insert_row(db_conn, table, data):
    try:
        cursor = db_conn.execute(
            'INSERT INTO {0} ({1}) VALUES ({2})'.format(table, ', '.join(data.keys()), ', '.join(['?'] * len(data))),
            tuple(data.values())
        )
        return cursor.lastrowid
    except Exception as e:
        print('SQLite-error:', e, data)
        return None


def update_row(db_conn, table, id, data):
    try:
        db_conn.execute(
            'UPDATE {0} SET {1} WHERE id = ?'.format(table, ', '.join([k + ' = ?' for k in data])),
            tuple(data.values()) + (id,)
        )
    except Exception as e:
        print('SQLite-error:', e, data)


class Manga:
    _chapters = None
    _server = None

    STATUSES = dict(
        complete=_('Complete'),
        ongoing=_('Ongoing'),
        suspended=_('Suspended'),
        hiatus=_('Hiatus'),
    )

    def __init__(self, server=None):
        if server:
            self._server = server

    @classmethod
    def get(cls, id, server=None):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT * FROM mangas WHERE id = ?', (id,)).fetchone()
        db_conn.close()

        if row is None:
            return None

        manga = cls(server=server)
        for key in row.keys():
            setattr(manga, key, row[key])

        return manga

    @classmethod
    def new(cls, data, server=None):
        manga = cls(server=server)

        data = data.copy()
        chapters = data.pop('chapters')
        cover_url = data.pop('cover')

        # Fill data with internal data or later scraped values
        data.update(dict(
            last_read=datetime.datetime.now(),
            sort_order=None,
            reading_direction=None,
            last_update=None,
        ))

        for key in data:
            setattr(manga, key, data[key])

        db_conn = create_db_connection()
        with db_conn:
            manga.id = insert_row(db_conn, 'mangas', data)

            manga._chapters = []
            rank = 0
            for chapter_data in chapters:
                chapter = Chapter.new(chapter_data, rank, manga.id, db_conn)
                if chapter is not None:
                    manga._chapters = [chapter, ] + manga._chapters
                    rank += 1

        db_conn.close()

        if not os.path.exists(manga.path):
            os.makedirs(manga.path)

        manga._save_cover(cover_url)

        return manga

    @property
    def chapters(self):
        if self._chapters is None:
            db_conn = create_db_connection()
            if self.sort_order == 'asc':
                rows = db_conn.execute('SELECT * FROM chapters WHERE manga_id = ? ORDER BY rank ASC', (self.id,))
            else:
                rows = db_conn.execute('SELECT * FROM chapters WHERE manga_id = ? ORDER BY rank DESC', (self.id,))

            self._chapters = []
            for row in rows:
                self._chapters.append(Chapter(row=row))

            db_conn.close()

        return self._chapters

    @property
    def cover_fs_path(self):
        path = os.path.join(self.path, 'cover.jpg')
        if os.path.exists(path):
            return path

        return None

    @property
    def nb_downloaded_chapters(self):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT count() AS downloaded FROM chapters WHERE manga_id = ? AND downloaded = 1', (self.id,)).fetchone()
        db_conn.close()

        return row['downloaded']

    @property
    def nb_recent_chapters(self):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT count() AS recents FROM chapters WHERE manga_id = ? AND recent = 1', (self.id,)).fetchone()
        db_conn.close()

        return row['recents']

    @property
    def path(self):
        return os.path.join(get_data_dir(), self.server_id, self.name)

    @property
    def server(self):
        if self._server is None:
            module_name = self.server_id.split('_')[0]
            module = importlib.import_module('.' + module_name, package='komikku.servers')
            self._server = getattr(module, self.server_id.capitalize())()

        return self._server

    def _save_cover(self, url):
        if url is None:
            return

        # Save cover image file
        cover_data = self.server.get_manga_cover_image(url)
        if cover_data is None:
            return

        cover_fs_path = os.path.join(self.path, 'cover.jpg')

        with open(cover_fs_path, 'wb') as fp:
            fp.write(cover_data)

    def delete(self):
        db_conn = create_db_connection()
        # Enable integrity constraint
        db_conn.execute('PRAGMA foreign_keys = ON')

        with db_conn:
            db_conn.execute('DELETE FROM mangas WHERE id = ?', (self.id, ))

            if os.path.exists(self.path):
                shutil.rmtree(self.path)

        db_conn.close()

    def get_next_chapter(self, chapter, direction=1):
        """
        :param chapter: reference chapter
        :param direction: -1 for preceding chapter, 1 for following chapter
        """
        assert direction in (-1, 1), 'Invalid direction value'

        db_conn = create_db_connection()
        if direction == 1:
            row = db_conn.execute(
                'SELECT * FROM chapters WHERE manga_id = ? AND rank > ? ORDER BY rank ASC', (self.id, chapter.rank)).fetchone()
        else:
            row = db_conn.execute(
                'SELECT * FROM chapters WHERE manga_id = ? AND rank < ? ORDER BY rank DESC', (self.id, chapter.rank)).fetchone()
        db_conn.close()

        if not row:
            return None

        return Chapter(row=row)

    def update(self, data):
        """
        Updates specific fields

        :param dict data: fields to update
        :return: True on success False otherwise
        """
        # Update
        for key in data:
            setattr(self, key, data[key])

        db_conn = create_db_connection()
        with db_conn:
            update_row(db_conn, 'mangas', self.id, data)

        db_conn.close()

        return True

    def update_full(self):
        """
        Updates manga

        Fetches and saves data available in manga's HTML page on server

        :return: True on success False otherwise, number of recent chapters
        :rtype: tuple
        """
        data = self.server.get_manga_data(dict(slug=self.slug, url=self.url))
        if data is None:
            return False, 0

        db_conn = create_db_connection()
        with db_conn:
            # Update cover
            cover = data.pop('cover')
            if cover:
                self._save_cover(cover)

            # Update chapters
            chapters_data = data.pop('chapters')
            nb_recent_chapters = 0

            rank = 0
            for chapter_data in chapters_data:
                row = db_conn.execute(
                    'SELECT * FROM chapters WHERE manga_id = ? AND slug = ?', (self.id, chapter_data['slug'])
                ).fetchone()
                if row:
                    # Update chapter
                    chapter_data['rank'] = rank
                    update_row(db_conn, 'chapters', row['id'], chapter_data)
                    rank += 1
                else:
                    # Add new chapter
                    chapter_data.update(dict(
                        manga_id=self.id,
                        rank=rank,
                        downloaded=0,
                        recent=1,
                        read=0,
                    ))
                    id = insert_row(db_conn, 'chapters', chapter_data)
                    if id is not None:
                        nb_recent_chapters += 1
                        rank += 1

            if nb_recent_chapters > 0:
                data['last_update'] = datetime.datetime.now()

            # Delete chapters that no longer exist
            chapters_slugs = [chapter_data['slug'] for chapter_data in chapters_data]
            rows = db_conn.execute('SELECT * FROM chapters WHERE manga_id = ?', (self.id,))
            for row in rows:
                if row['slug'] not in chapters_slugs:
                    db_conn.execute('DELETE FROM chapters WHERE id = ?', (row['id'],))

            self._chapters = None

            # Store old path
            old_path = self.path

            # Update
            for key in data:
                setattr(self, key, data[key])

            update_row(db_conn, 'mangas', self.id, data)

            if old_path != self.path:
                # Manga name changes, manga folder must be renamed too
                os.rename(old_path, self.path)

        db_conn.close()

        return True, nb_recent_chapters


class Chapter:
    _manga = None

    def __init__(self, row=None):
        if row is not None:
            for key in row.keys():
                setattr(self, key, row[key])

    @classmethod
    def get(cls, id):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT * FROM chapters WHERE id = ?', (id,)).fetchone()
        db_conn.close()

        if row is None:
            return None

        c = cls()
        for key in row.keys():
            setattr(c, key, row[key])

        return c

    @classmethod
    def new(cls, data, rank, manga_id, db_conn=None):
        c = cls()

        # Fill data with internal usage data or not yet scraped values
        data = data.copy()
        data.update(dict(
            manga_id=manga_id,
            pages=None,   # later scraped value
            scrambled=0,  # later scraped value
            rank=rank,
            downloaded=0,
            recent=0,
            read=0,
            last_page_read_index=None,
        ))

        for key in data:
            setattr(c, key, data[key])

        if db_conn is not None:
            c.id = insert_row(db_conn, 'chapters', data)
        else:
            db_conn = create_db_connection()
            with db_conn:
                c.id = insert_row(db_conn, 'chapters', data)

            db_conn.close()

        return c if c.id is not None else None

    @property
    def manga(self):
        if self._manga is None:
            self._manga = Manga.get(self.manga_id)

        return self._manga

    @property
    def path(self):
        # BEWARE: self.slug may contain '/' characters
        # os.makedirs() must be used to create chapter's folder
        return os.path.join(self.manga.path, self.slug)

    def get_page(self, page_index):
        page_path = self.get_page_path(page_index)
        if page_path:
            return page_path

        imagename, data = self.manga.server.get_manga_chapter_page_image(
            self.manga.slug, self.manga.name, self.slug, self.pages[page_index])
        if data is None:
            return None

        if not os.path.exists(self.path):
            os.makedirs(self.path)

        page_path = os.path.join(self.path, imagename)

        if self.scrambled:
            with open(page_path + '_scrambled', 'wb') as fp:
                fp.write(data)

            unscramble_image(page_path + '_scrambled', page_path)
        else:
            with open(page_path, 'wb') as fp:
                fp.write(data)

        if self.pages[page_index]['image'] is None:
            self.pages[page_index]['image'] = imagename
            self.update(dict(pages=self.pages))

        return page_path

    def get_page_path(self, page_index):
        if self.pages[page_index]['image'] is not None:
            # self.pages[page_index]['image'] can be an image name or an image url (path + eventually a query string)

            # Extract filename
            imagename = self.pages[page_index]['image'].split('/')[-1]
            # Remove query string
            imagename = imagename.split('?')[0]

            path = os.path.join(self.path, imagename)

            return path if os.path.exists(path) else None

        return None

    def reset(self):
        if os.path.exists(self.path):
            shutil.rmtree(self.path)

        self.update(dict(
            pages=None,
            downloaded=0,
            read=0,
            last_page_read_index=None,
        ))

    def update(self, data):
        """
        Updates specific fields

        :param dict data: fields to update
        :return: True on success False otherwise
        """
        for key in data:
            setattr(self, key, data[key])

        db_conn = create_db_connection()
        with db_conn:
            update_row(db_conn, 'chapters', self.id, data)

        db_conn.close()

        return True

    def update_full(self):
        """
        Updates chapter

        Fetches and saves data available in chapter's HTML page on server

        :return: True on success False otherwise
        """
        if self.pages:
            return True

        data = self.manga.server.get_manga_chapter_data(self.manga.slug, self.slug, self.url)
        if data is None:
            return False

        return self.update(data)


class Download:
    _chapter = None

    STATUSES = dict(
        pending=_('Download pending'),
        downloading=_('Downloading'),
        error=_('Error'),
    )

    @classmethod
    def get(cls, id):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT * FROM downloads WHERE id = ?', (id,)).fetchone()
        db_conn.close()

        if row is None:
            return None

        d = cls()
        for key in row.keys():
            setattr(d, key, row[key])

        return d

    @classmethod
    def get_by_chapter_id(cls, chapter_id):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT * FROM downloads WHERE chapter_id = ?', (chapter_id,)).fetchone()
        db_conn.close()

        if row:
            d = cls()

            for key in row.keys():
                setattr(d, key, row[key])

            return d

        return None

    @classmethod
    def new(cls, chapter_id):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT * FROM downloads WHERE chapter_id = ?', (chapter_id,)).fetchone()
        db_conn.close()
        if row:
            return None

        d = cls()
        data = dict(
            chapter_id=chapter_id,
            status='pending',
            percent=0,
            date=datetime.datetime.now(),
        )

        for key in data:
            setattr(d, key, data[key])

        db_conn = create_db_connection()
        with db_conn:
            d.id = insert_row(db_conn, 'downloads', data)

        db_conn.close()

        return d

    @property
    def chapter(self):
        if self._chapter is None:
            self._chapter = Chapter.get(self.chapter_id)

        return self._chapter

    def delete(self):
        db_conn = create_db_connection()
        # Enable integrity constraint
        db_conn.execute('PRAGMA foreign_keys = ON')

        with db_conn:
            db_conn.execute('DELETE FROM downloads WHERE id = ?', (self.id, ))

        db_conn.close()

    def update(self, data):
        """
        Updates download

        :param data: percent of pages downloaded and/or status
        :return: True on success False otherwise
        """

        db_conn = create_db_connection()
        with db_conn:
            update_row(db_conn, 'downloads', self.id, data)

        db_conn.close()

        return True
