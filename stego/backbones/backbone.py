import torch
import torch.nn.functional as F
from .dino import vision_transformer as vits
from torch import nn
import numpy as np
import abc
from abc import ABC, abstractmethod


def get_backbone(cfg):
    """
    Returns a selected STEGO backbone.
    After implementing the Backbone class for your backbone, add it to be returned from this function with a desired named.
    The backbone can then be used by specifying its name in the STEGO configuration file.
    """
    if cfg.backbone == "dino":
        return DinoViT(cfg)
    elif cfg.backbone == "dinov2":
        return Dinov2ViT(cfg)
    else:
        raise ValueError("Backbone {} unavailable".format(cfg.backbone))
    

class Backbone(ABC, nn.Module):
    """
    Base class to provide an interface for new STEGO backbones.

    To add a new backbone for use in STEGO, add a new implementation of this class.
    """

    vit_name_long_to_short = {
        "vit_tiny": "T",
        "vit_small": "S",
        "vit_base": "B",
        "vit_large": "L",
        "vit_huge": "H",
        "vit_giant": "G"
    }

    # Initialize the backbone
    @abstractmethod
    def __init__(self, cfg):
        super().__init__()
    
    # Return the size of features generated by the backbone
    @abstractmethod
    def get_output_feat_dim(self) -> int:
        pass

    # Generate features for the given image
    @abstractmethod
    def forward(self, img):
        pass

    # Returh a name that identifies the type of the backbone
    @abstractmethod
    def get_backbone_name(self):
        pass

class Dinov2ViT(Backbone):

    def __init__(self, cfg):
        super().__init__(cfg)
        self.cfg = cfg
        self.model_type = self.cfg.backbone_type
        self.patch_size = 14
        if cfg.backbone_type == "vit_small":
            self.model = torch.hub.load('facebookresearch/dinov2', 'dinov2_vits14')
        elif cfg.backbone_type == "vit_base":
            self.model = torch.hub.load('facebookresearch/dinov2', 'dinov2_vitb14')
        else:
            raise ValueError("Model type {} unavailable".format(cfg.backbone_type))

        for p in self.model.parameters():
            p.requires_grad = False
        self.model.eval().cuda()
        self.dropout = torch.nn.Dropout2d(p=np.clip(self.cfg.dropout_p, 0.0, 1.0))

        if self.model_type == "vit_small":
            self.n_feats = 384
        else:
            self.n_feats = 768

    def get_output_feat_dim(self):
        return self.n_feats

    def forward(self, img):
        self.model.eval()
        with torch.no_grad():
            assert (img.shape[2] % self.patch_size == 0)
            assert (img.shape[3] % self.patch_size == 0)

            # get selected layer activations
            feat = self.model.get_intermediate_layers(img)[0]

            feat_h = img.shape[2] // self.patch_size
            feat_w = img.shape[3] // self.patch_size

            image_feat = feat[:, :, :].reshape(feat.shape[0], feat_h, feat_w, -1).permute(0, 3, 1, 2)

        if self.cfg.dropout_p > 0:
            return self.dropout(image_feat)
        else:
            return image_feat
        
    def get_backbone_name(self):
        return "DINOv2-"+Backbone.vit_name_long_to_short[self.model_type]+"-"+str(self.patch_size)


class DinoViT(Backbone):

    def __init__(self, cfg):
        super().__init__(cfg)
        self.cfg = cfg
        self.patch_size = self.cfg.patch_size
        self.model_type = self.cfg.backbone_type
        self.model = vits.__dict__[self.model_type](
            patch_size=self.patch_size,
            num_classes=0)
        for p in self.model.parameters():
            p.requires_grad = False
        self.model.eval().cuda()
        self.dropout = torch.nn.Dropout2d(p=np.clip(self.cfg.dropout_p, 0.0, 1.0))

        if self.model_type == "vit_small" and self.patch_size == 16:
            url = "dino_deitsmall16_pretrain/dino_deitsmall16_pretrain.pth"
        elif self.model_type == "vit_small" and self.patch_size == 8:
            url = "dino_deitsmall8_300ep_pretrain/dino_deitsmall8_300ep_pretrain.pth"
        elif self.model_type == "vit_base" and self.patch_size == 16:
            url = "dino_vitbase16_pretrain/dino_vitbase16_pretrain.pth"
        elif self.model_type == "vit_base" and self.patch_size == 8:
            url = "dino_vitbase8_pretrain/dino_vitbase8_pretrain.pth"
        else:
            raise ValueError("Model type {} unavailable with patch size {}".format(self.model_type, self.patch_size))

        if cfg.pretrained_weights is not None:
            state_dict = torch.load(cfg.pretrained_weights, map_location="cpu")
            # remove `module.` prefix
            state_dict = {k.replace("module.", ""): v for k, v in state_dict.items()}
            # remove `backbone.` prefix induced by multicrop wrapper
            state_dict = {k.replace("backbone.", ""): v for k, v in state_dict.items()}
            msg = self.model.load_state_dict(state_dict, strict=False)
            print('Pretrained weights found at {} and loaded with msg: {}'.format(cfg.pretrained_weights, msg))
        else:
            print("Since no pretrained weights have been provided, we load the reference pretrained DINO weights.")
            state_dict = torch.hub.load_state_dict_from_url(url="https://dl.fbaipublicfiles.com/dino/" + url)
            self.model.load_state_dict(state_dict, strict=True)

        if self.model_type == "vit_small":
            self.n_feats = 384
        else:
            self.n_feats = 768

    def get_output_feat_dim(self):
        return self.n_feats

    def forward(self, img):
        self.model.eval()
        with torch.no_grad():
            assert (img.shape[2] % self.patch_size == 0)
            assert (img.shape[3] % self.patch_size == 0)

            # get selected layer activations
            feat, attn, qkv = self.model.get_intermediate_feat(img)
            feat, attn, qkv = feat[0], attn[0], qkv[0]

            feat_h = img.shape[2] // self.patch_size
            feat_w = img.shape[3] // self.patch_size

            image_feat = feat[:, 1:, :].reshape(feat.shape[0], feat_h, feat_w, -1).permute(0, 3, 1, 2)

        if self.cfg.dropout_p > 0:
            return self.dropout(image_feat)
        else:
            return image_feat
    
    def get_backbone_name(self):
        return "DINO-"+Backbone.vit_name_long_to_short[self.model_type]+"-"+str(self.patch_size)