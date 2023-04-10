# SPDX-FileCopyrightText: Copyright (c) 2023, Dask Developers, Yuvi Panda, Anaconda Inc, NVIDIA
# SPDX-License-Identifier: BSD 3-Clause License
import asyncio

import aiohttp
import pytest

import kr8s
from kr8s.objects import (
    APIObject,
    Deployment,
    Pod,
    Service,
    get_class,
    object_from_spec,
)


async def test_pod_create_and_delete(example_pod_spec):
    pod = Pod(example_pod_spec)
    await pod.create()
    with pytest.raises(NotImplementedError):
        pod.replicas
    assert await pod.exists()
    while not await pod.ready():
        await asyncio.sleep(0.1)
    await pod.delete()
    while await pod.exists():
        await asyncio.sleep(0.1)
    assert not await pod.exists()


async def test_list_and_ensure():
    kubernetes = kr8s.api()
    pods = await kubernetes.get("pods", namespace=kr8s.ALL)
    assert len(pods) > 0
    for pod in pods:
        await pod.refresh()
        assert await pod.exists(ensure=True)


async def test_nonexistant():
    pod = Pod(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "nonexistant",
                "namespace": "nonexistant",
            },
        }
    )
    assert not await pod.exists()
    with pytest.raises(kr8s.NotFoundError):
        await pod.exists(ensure=True)


async def test_pod_metadata(example_pod_spec):
    pod = Pod(example_pod_spec)
    await pod.create()
    assert "name" in pod.metadata
    assert "hello" in pod.labels
    assert "foo" in pod.annotations
    assert "default" == pod.namespace
    assert "example-" in pod.name
    assert "containers" in pod.spec
    assert "phase" in pod.status
    await pod.delete()


async def test_pod_missing_labels_annotations(example_pod_spec):
    del example_pod_spec["metadata"]["labels"]
    del example_pod_spec["metadata"]["annotations"]
    pod = Pod(example_pod_spec)
    await pod.create()
    assert not pod.labels
    assert not pod.annotations
    await pod.delete()


async def test_pod_get(example_pod_spec):
    pod = Pod(example_pod_spec)
    await pod.create()
    pod2 = await Pod.get(pod.name, namespace=pod.namespace)
    assert pod2.name == pod.name
    assert pod2.namespace == pod.namespace
    await pod.delete()
    while await pod.exists():
        await asyncio.sleep(0.1)
    with pytest.raises(kr8s.NotFoundError):
        await pod2.delete()


async def test_pod_watch(example_pod_spec):
    pod = Pod(example_pod_spec)
    await pod.create()
    async for event, obj in pod.watch():
        assert event in ("ADDED", "MODIFIED", "DELETED")
        assert obj.name == pod.name
        break
    await pod.delete()


async def test_patch_pod(example_pod_spec):
    pod = Pod(example_pod_spec)
    await pod.create()
    assert "patched" not in pod.labels
    await pod.patch({"metadata": {"labels": {"patched": "true"}}})
    assert "patched" in pod.labels
    await pod.delete()


async def test_all_v1_objects_represented():
    kubernetes = kr8s.api()
    objects = await kubernetes.api_resources()
    supported_apis = (
        "v1",
        "apps/v1",
        "autoscaling/v2",
        "batch/v1",
        "networking.k8s.io/v1",
        "policy/v1",
        "rbac.authorization.k8s.io/v1",
        "apiextensions.k8s.io/v1",
    )
    # for supported_api in supported_apis:
    #     assert supported_api in [obj["version"] for obj in objects]
    objects = [obj for obj in objects if obj["version"] in supported_apis]
    for obj in objects:
        assert get_class(obj["kind"], obj["version"])


async def test_object_from_spec(example_pod_spec, example_service_spec):
    pod = object_from_spec(example_pod_spec)
    assert isinstance(pod, Pod)
    assert pod.name == example_pod_spec["metadata"]["name"]
    assert pod.spec == example_pod_spec["spec"]

    service = object_from_spec(example_service_spec)
    assert isinstance(service, Service)
    assert service.name == example_service_spec["metadata"]["name"]
    assert service.spec == example_service_spec["spec"]


async def test_subclass_registration():
    with pytest.raises(KeyError):
        get_class("MyResource", "foo.kr8s.org/v1alpha1")

    class MyResource(APIObject):
        version = "foo.kr8s.org/v1alpha1"
        endpoint = "myresources"
        kind = "MyResource"
        plural = "myresources"
        singular = "myresource"
        namespaced = True

    get_class("MyResource", "foo.kr8s.org/v1alpha1")


async def test_deployment_scale(example_deployment_spec):
    deployment = Deployment(example_deployment_spec)
    await deployment.create()
    assert deployment.replicas == 1
    await deployment.scale(2)
    assert deployment.replicas == 2
    while not await deployment.ready():
        await asyncio.sleep(0.1)
    await deployment.scale(1)
    assert deployment.replicas == 1
    await deployment.delete()


async def test_node():
    kubernetes = kr8s.api()
    nodes = await kubernetes.get("nodes")
    assert len(nodes) > 0
    for node in nodes:
        assert node.unschedulable is False
        await node.cordon()
        assert node.unschedulable is True
        await node.uncordon()


async def test_service_proxy():
    kubernetes = kr8s.api()
    [service] = await kubernetes.get("services", "kubernetes")
    assert service.name == "kubernetes"
    data = await service.proxy_http_get("/version", raise_for_status=False)
    assert isinstance(data, aiohttp.ClientResponse)


async def test_pod_logs(example_pod_spec):
    pod = Pod(example_pod_spec)
    await pod.create()
    while not await pod.ready():
        await asyncio.sleep(0.1)
    log = await pod.logs(container="pause")
    assert isinstance(log, str)
    await pod.delete()