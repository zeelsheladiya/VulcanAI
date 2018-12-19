"""Test all ConvNet capabilities."""
import pytest
import numpy as np
import copy
import pickle
import logging
import os
import shutil

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Subset, TensorDataset
from torch.autograd import gradcheck

from vulcanai2.models import BaseNetwork
from vulcanai2.models.cnn import ConvNet, ConvNetConfig
from vulcanai2.models.utils import master_device_setter

logger = logging.getLogger(__name__)

class TestConvNet:
    """Define ConvNet test class."""
    
    @pytest.fixture
    def multi_input_train_loader(self, multi_input_cnn_data):
        test_train = Subset(multi_input_cnn_data, 
                            range(len(multi_input_cnn_data)//2))
        return DataLoader(test_train, batch_size=2) 

    @pytest.fixture
    def multi_input_test_loader(self, multi_input_cnn_data):
        test_val = Subset(multi_input_cnn_data, 
                          range(len(multi_input_cnn_data)//2, 
                                    len(multi_input_cnn_data)))
        return DataLoader(test_val, batch_size=2)  

    def test_init(self, conv1D_net):
        """Initialization Test of a ConvNet object"""
        assert isinstance(conv1D_net, BaseNetwork)
        assert isinstance(conv1D_net, nn.Module)
        assert hasattr(conv1D_net, 'network')
        assert hasattr(conv1D_net, 'in_dim')
        assert hasattr(conv1D_net, 'record')
        assert hasattr(conv1D_net, 'device')

        assert conv1D_net._name is not None
        assert isinstance(conv1D_net._config, ConvNetConfig)

        assert conv1D_net.input_networks is None
        assert conv1D_net.epoch == 0
        assert conv1D_net.optim is None
        assert conv1D_net.criterion is None
        
        assert not hasattr(conv1D_net, 'metrics')

    def test_function_multi_input(self, multi_input_cnn):
        """Test functions wrt multi_input_cnn"""
        assert isinstance(multi_input_cnn.input_networks, nn.ModuleDict)
        assert len(list(multi_input_cnn.input_networks)) == 3
        assert all(multi_input_cnn._get_max_incoming_spatial_dims() == (8, 8, 8))
        assert multi_input_cnn._merge_input_network_outputs([
                                torch.ones([10, 1, 28, 28]),
                                torch.ones([10, 1, 28, 28, 28]),
                                torch.ones(10, *multi_input_cnn.\
                                input_networks['multi_input_dnn'].out_dim)
               ]).shape == (10, 3, 8, 8, 8)
    
    def test_forward(self, conv1D_net):
        """Test Forward of ConvNet"""
        out = conv1D_net(torch.ones([10, *conv1D_net.in_dim]))
        assert out.shape == (10, 64, 1)

    def test_forward_multi_input(self, multi_input_cnn, conv1D_net):
        """Test Forward of Multi Input ConvNet"""
        master_device_setter(multi_input_cnn, 'cpu')
        input_tensor = [torch.ones([10, 1, 28, 28]),
               torch.ones([10, 1, 28, 28, 28]),
               [torch.ones([10, 1, 28]),
                torch.ones([10, 1, 28, 28])]
            ]
        out = multi_input_cnn(input_tensor)
        assert out.shape == (10, 10)
        inp = torch.ones([10, 1, 28], requires_grad=True)
        for net in conv1D_net.network:
            import pdb; pdb.set_trace()
            if net._kernel:
                import pdb; pdb.set_trace()
                # Kernel
                assert gradcheck(net._kernel.double(), (inp.double(),))
                inp = net._kernel.double()(inp.double())
            if net._activation:
                import pdb; pdb.set_trace()
                # Activation
                assert gradcheck(net._activation.double(), (inp.double(),))
                inp = net._activation.double()(inp.double())
            if net._pool:
                import pdb; pdb.set_trace()
                # Pool
                # TODO failing here: RuntimeError: Jacobian mismatch for output 0 with respect to input 0,
                assert gradcheck(net._pool.double(), (inp.double(),))
                inp = net._pool.double()(inp.double())
            if net._dropout:
                import pdb; pdb.set_trace()
                # TODO failing here too assuming if Pool passes: RuntimeError: Jacobian mismatch for output 0 with respect to input 0,
                # Dropout
                assert gradcheck(net._dropout.double(), (inp.double(),))
                inp = net._dropout.double()(inp.double())

    def test_forward_pass_not_nan(self, conv3D_net):
        """Confirm out is non nan."""
        test_input = torch.ones([1, *conv3D_net.in_dim])
        test_dataloader = DataLoader(TensorDataset(test_input, test_input))
        output = conv3D_net.forward_pass(
            data_loader=test_dataloader,
            convert_to_class=False)
        assert np.any(~np.isnan(output))

    def test_forward_pass_class_not_nan(self, conv3D_net_class):
        """Confirm out is non nan."""
        test_input = torch.ones([1, *conv3D_net_class.in_dim])
        test_dataloader = DataLoader(TensorDataset(test_input, test_input))
        raw_output = conv3D_net_class.forward_pass(
            data_loader=test_dataloader,
            convert_to_class=False)
        class_output = conv3D_net_class.metrics.extract_class_labels(
            in_matrix=raw_output)
        assert np.any(~np.isnan(class_output))
        assert np.any(~np.isnan(raw_output))

    def test_freeze_class(self, conv3D_net_class):
        """Test class network freezing."""
        conv3D_net_class.freeze(apply_inputs=False)
        for params in conv3D_net_class.network.parameters():
            assert params.requires_grad is False

    def test_unfreeze_class(self, conv3D_net_class):
        """Test class network unfreezing."""
        conv3D_net_class.freeze(apply_inputs=False)
        conv3D_net_class.unfreeze(apply_inputs=False)
        for params in conv3D_net_class.network.parameters():
            assert params.requires_grad is True

    def test_freeze_noclass(self, conv3D_net):
        """Test intermediate network freezing."""
        conv3D_net.freeze(apply_inputs=False)
        for params in conv3D_net.network.parameters():
            assert params.requires_grad is False

    def test_unfreeze_noclass(self, conv3D_net):
        """Test intermediate network unfreezing."""
        conv3D_net.freeze(apply_inputs=False)
        conv3D_net.unfreeze(apply_inputs=False)
        for params in conv3D_net.network.parameters():
            assert params.requires_grad is True

    def test_fit_multi_input(self, multi_input_cnn,
                             multi_input_train_loader,
                             multi_input_test_loader):
        """Test for fit function"""        
        init_weights = copy.deepcopy(multi_input_cnn.network[0]._kernel.weight.detach())
        multi_input_cnn_no_fit = copy.deepcopy(multi_input_cnn)
        parameters1 = multi_input_cnn_no_fit.parameters()
        try:
            multi_input_cnn.fit(multi_input_train_loader, 
                                multi_input_test_loader, 2)
        except RuntimeError:
            logger.error("The network multi_input_cnn failed to train.")
        finally:
            parameters2 = multi_input_cnn.parameters()
            trained_weights = multi_input_cnn.network[0]._kernel.weight.detach()
            
            # Sanity check if the network parameters are training
            assert (torch.equal(init_weights.cpu(), trained_weights.cpu()) is False)
            compare_params = [not torch.allclose(param1, param2)
                        for param1, param2 in zip(parameters1,
                                                  parameters2)]
            assert all(compare_params)
    
    def test_params_multi_input(self, multi_input_cnn,
                                multi_input_train_loader,
                                multi_input_test_loader):
        """Test for change in network params/specifications"""
        
        test_net = pickle.loads(pickle.dumps(multi_input_cnn))
        
        # Check the parameters are copying properly
        copy_params = [torch.allclose(param1, param2)
                        for param1, param2 in zip(multi_input_cnn.parameters(),
                                                  test_net.parameters())]
        assert all(copy_params)

        # Check the parameters change after copy and fit
        test_net.fit(multi_input_train_loader, 
                      multi_input_test_loader, 2)
        close_params = [not torch.allclose(param1, param2)
                        for param1, param2 in zip(multi_input_cnn.parameters(),
                                                  test_net.parameters())]
        assert all(close_params)

        # Check the network params and optimizer params point to
        # the same memory
        if test_net.optim:
            assert isinstance(test_net.optim, torch.optim.Adam)
            assert isinstance(test_net.criterion, torch.nn.CrossEntropyLoss)
            for param, opt_param in zip(test_net.parameters(),
                                        test_net.optim.param_groups[0]['params']):
                assert param is opt_param
        
        # Check the params after saving loaading
        test_net.save_model()
        save_path = test_net.save_path
        abs_save_path = os.path.dirname(os.path.abspath(save_path))
        loaded_test_net = BaseNetwork.load_model(load_path=save_path)
        load_params = [torch.allclose(param1, param2)
                        for param1, param2 in zip(test_net.parameters(),
                                                  loaded_test_net.parameters())]
        shutil.rmtree(abs_save_path)
        assert all(load_params)
    
    # TODO: Add a private function test for _add_input_network