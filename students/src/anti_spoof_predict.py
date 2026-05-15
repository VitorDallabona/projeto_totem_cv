# -*- coding: utf-8 -*-
# @Time : 20-6-9 上午10:20
# @Author : zhuying
# @Company : Minivision
# @File : anti_spoof_predict.py
# @Software : PyCharm

import os
import traceback

import cv2
import math
import torch
import numpy as np
import torch.nn.functional as F

from students.src.model_lib.MiniFASNet import (
    MiniFASNetV1,
    MiniFASNetV2,
    MiniFASNetV1SE,
    MiniFASNetV2SE
)
from students.src.data_io import transform as trans
from students.src.utility import (
    get_kernel,
    parse_model_name
)


MODEL_MAPPING = {
    'MiniFASNetV1': MiniFASNetV1,
    'MiniFASNetV2': MiniFASNetV2,
    'MiniFASNetV1SE': MiniFASNetV1SE,
    'MiniFASNetV2SE': MiniFASNetV2SE
}


class Detection:
    def __init__(self):
        stack = traceback.extract_stack()
        dirname = os.path.dirname(stack[-2].filename)

        caffemodel = os.path.join(
            dirname,
            '..',
            'resources',
            'detection_model',
            'Widerface-RetinaFace.caffemodel'
        )
        
        deploy = os.path.join(
            dirname,
            '..',
            'resources',
            'detection_model',
            'deploy.prototxt'
        )

        self.detector = None
        
        self.detector_confidence = 0.9

    def get_bbox(
        self,
        img
    ):
        height, width = img.shape[0], img.shape[1]
        aspect_ratio = width / height
        
        if img.shape[1] * img.shape[0] >= 192 * 192:
            img = cv2.resize(
                img,
                (
                    int(192 * math.sqrt(aspect_ratio)),
                    int(192 / math.sqrt(aspect_ratio))
                ),
                interpolation=cv2.INTER_LINEAR
            )

        blob = cv2.dnn.blobFromImage(
            img,
            1,
            mean=(104, 117, 123)
        )
        
        self.detector.setInput(
            blob,
            'data'
        )
        
        out = self.detector.forward(
            'detection_out'
        ).squeeze()
        
        max_conf_index = np.argmax(out[:, 2])
        
        left = out[max_conf_index, 3] * width
        top = out[max_conf_index, 4] * height
        right = out[max_conf_index, 5] * width
        bottom = out[max_conf_index, 6] * height
        
        bbox = [
            int(left),
            int(top),
            int(right - left + 1),
            int(bottom - top + 1)
        ]
        
        return bbox


class AntiSpoofPredict(Detection):
    def __init__(
        self,
        device_id
    ):
        super(AntiSpoofPredict, self).__init__()
        
        self.device = torch.device(
            "cuda:{}".format(device_id)
            if torch.cuda.is_available()
            else "cpu"
        )
        
        # MELHORIA: Dicionario para armazenar multiplos modelos simultaneamente
        self.loaded_models = {}

    def _load_model(
        self,
        model_path
    ):
        model_name = os.path.basename(model_path)
        
        h_input, w_input, model_type, _ = parse_model_name(model_name)
        
        kernel_size = get_kernel(
            h_input,
            w_input,
        )
        
        # Instancia o modelo localmente em vez de usar self.model
        model = MODEL_MAPPING[model_type](
            conv6_kernel=kernel_size
        ).to(self.device)

        state_dict = torch.load(
            model_path,
            map_location=self.device,
            weights_only=True
        )
        
        keys = iter(state_dict)
        first_layer_name = keys.__next__()
        
        if first_layer_name.find('module.') >= 0:
            from collections import OrderedDict
            new_state_dict = OrderedDict()
            
            for key, value in state_dict.items():
                name_key = key[7:]
                new_state_dict[name_key] = value
                
            model.load_state_dict(new_state_dict)
        else:
            model.load_state_dict(state_dict)
            
        return model

    def predict(
        self,
        img,
        model_path
    ):
        test_transform = trans.Compose([
            trans.ToTensor(),
        ])
        
        img = test_transform(img)
        img = img.unsqueeze(0).to(self.device)
        
        # Se o modelo ainda nao estiver no dicionario, faz o carregamento
        if model_path not in self.loaded_models:
            self.loaded_models[model_path] = self._load_model(model_path)
            
        # Puxa o modelo direto da memoria RAM/VRAM
        model_instance = self.loaded_models[model_path]
        model_instance.eval()
        
        with torch.no_grad():
            result = model_instance.forward(img)
            
            result = F.softmax(
                result,
                dim=1
            ).cpu().numpy()

        return result