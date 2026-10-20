"""Battlecode control-plane authority and immutable source receipts."""
import base64
import threading
import time
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from sandbox_controller.artifacts import ArtifactStore
from sandbox_controller.service import Controller,BattlecodeCompile,BattlecodeMatch

OWNER='a'*32
LEASE='b'*32


def test_battlecode_source_artifact_digest_and_image_binding(tmp_path):
    store=ArtifactStore(tmp_path)
    source=b'def turn():\n    pass\n'
    receipt=store.save_battlecode('bc-source','py',source,'image-one')
    assert base64.b64decode(store.load_battlecode(receipt['artifact_id'],receipt['artifact_digest'],'image-one')['source'])==source
    with pytest.raises(ValueError):store.load_battlecode(receipt['artifact_id'],receipt['artifact_digest'],'image-two')
    (tmp_path/'bc-source.bc.json').write_bytes(b'changed')
    with pytest.raises(ValueError):store.load_battlecode(receipt['artifact_id'],receipt['artifact_digest'],'image-one')
    with pytest.raises(ValueError):store.save_battlecode('../escape','py',source,'image-one')


def test_battlecode_rejects_caller_docker_options_and_arbitrary_maps():
    with pytest.raises(ValidationError):BattlecodeCompile(owner=OWNER,lease=LEASE,language='py',source='eA==',image='anything')
    with pytest.raises(ValidationError):BattlecodeCompile(owner=OWNER,lease=LEASE,language='cpp',source='eA==')
    with pytest.raises(ValidationError):BattlecodeMatch(owner=OWNER,lease=LEASE,artifact_a='a',digest_a='a'*64,artifact_b='b',digest_b='b'*64,map='../../outside')


def controller(tmp_path):
    control=Controller.__new__(Controller)
    control.lock=threading.RLock();control.owner=OWNER;control.lease=LEASE
    control.heartbeat=time.monotonic();control.retired_owners=set();control.used_ids=set();control.jobs={}
    control.store=ArtifactStore(tmp_path)
    return control


def test_battlecode_stale_lease_is_fenced_before_artifact_read(tmp_path):
    control=controller(tmp_path)
    control.engine=SimpleNamespace(battlecode_image='image-one')
    called=[]
    control.store.load_battlecode=lambda *args:called.append(args)
    payload=BattlecodeMatch(owner=OWNER,lease='f'*32,artifact_a='a',digest_a='a'*64,artifact_b='b',digest_b='b'*64,map='DefaultSmall')
    with pytest.raises(HTTPException) as error:control.battlecode('bc-run',payload,'match')
    assert error.value.status_code==409 and not called


def test_duplicate_battlecode_compile_returns_receipt_without_reexecution(tmp_path):
    control=controller(tmp_path);calls=[]
    container=SimpleNamespace(remove=lambda **kwargs:None)
    control.engine=SimpleNamespace(battlecode_image='image-one',run_battlecode=lambda *args:(calls.append(1) or {'status':'ready','logs':''}))
    def ensure(job_id,job):job.container=container
    control.ensure_container=ensure
    payload=BattlecodeCompile(owner=OWNER,lease=LEASE,language='py',source=base64.b64encode(b'def turn():\n    pass\n').decode())
    first=control.battlecode('bc-compile',payload,'compile')
    second=control.battlecode('bc-compile',payload,'compile')
    assert first==second and first['artifact_digest'] and calls==[1]
